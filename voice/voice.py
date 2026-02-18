"""
Voice recording and transcription for the Receipt library.
Supports local Whisper (faster-whisper) and OpenAI Whisper API.
"""

import os
import sys
import tempfile
import threading
import wave
from typing import Optional

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel


def _get_device_sample_rate() -> int:
    """Get the default input device's native sample rate."""
    try:
        device_info = sd.query_devices(kind='input')
        return int(device_info['default_samplerate'])
    except Exception:
        return 16000


def _resample(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Resample int16 audio using linear interpolation."""
    if from_rate == to_rate:
        return audio
    target_len = int(len(audio) * to_rate / from_rate)
    indices = np.linspace(0, len(audio) - 1, target_len)
    resampled = np.interp(indices, np.arange(len(audio)), audio.astype(np.float32))
    return resampled.astype(np.int16)

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from ..llm.costs import track_whisper_usage
except ImportError:
    from llm.costs import track_whisper_usage

try:
    from .vad import VoiceActivityDetector, trim_silence
    VAD_AVAILABLE = True
except ImportError:
    try:
        from vad import VoiceActivityDetector, trim_silence
        VAD_AVAILABLE = True
    except ImportError:
        VAD_AVAILABLE = False

try:
    from ..config import Config, default_config
except ImportError:
    from config import Config, default_config

class VoiceRecorder:
    """Records audio from microphone."""

    def __init__(self, config: Optional[Config] = None):
        """
        Initialize the voice recorder.

        Args:
            config: Configuration object
        """
        self.config = config or default_config
        self._device_rate = _get_device_sample_rate()
        self._stream = None
        self._frames = []
        self._recording = False

    def start_recording(self):
        """Start recording audio."""
        self._frames = []
        self._recording = True

        self._stream = sd.RawInputStream(
            samplerate=self._device_rate,
            channels=1,
            dtype='int16',
            blocksize=1024,
            callback=self._audio_callback
        )
        self._stream.start()
        print(f"[Recording at {self._device_rate}Hz...]")

    def _audio_callback(self, indata, frames, time, status):
        """Callback for audio stream."""
        if self._recording:
            self._frames.append(bytes(indata))

    def stop_recording(self, min_duration: float = 1.0) -> Optional[str]:
        """
        Stop recording and save to temporary file.

        Args:
            min_duration: Minimum recording duration in seconds (default 1.0)

        Returns:
            Path to the recorded audio file, or None if too short
        """
        self._recording = False

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        # Calculate duration: frames * buffer_size / device_rate
        duration = len(self._frames) * 1024 / self._device_rate

        if duration < min_duration:
            print(f"[Recording too short ({duration:.1f}s < {min_duration}s), cancelled]")
            self._frames = []
            return None

        print(f"[Recording stopped ({duration:.1f}s)]")

        # Resample to 16kHz for Whisper
        raw_audio = np.frombuffer(b''.join(self._frames), dtype=np.int16)
        audio_16k = _resample(raw_audio, self._device_rate, 16000)

        # Save to temporary WAV file
        temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        temp_path = temp_file.name
        temp_file.close()

        with wave.open(temp_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(16000)
            wf.writeframes(audio_16k.tobytes())

        self._frames = []
        return temp_path

    def cleanup(self):
        """Clean up audio resources."""
        if self._stream:
            self._stream.close()
            self._stream = None


class Transcriber:
    """Transcribes audio to text using Whisper."""

    def __init__(self, config: Optional[Config] = None):
        """
        Initialize the transcriber.

        Args:
            config: Configuration object
        """
        self.config = config or default_config
        self._local_model = None

    def preload_model(self):
        """Pre-load the Whisper model to avoid delay on first transcription."""
        if self.config.whisper_provider == 'local' and self._local_model is None:
            print(f"[Loading Whisper model: {self.config.whisper_model}]")
            self._local_model = self._load_whisper_model()
            print("[Model loaded]")

    def _load_whisper_model(self):
        """Load Whisper model, defaulting to CPU for reliability."""
        # Always use CPU - fast enough and avoids CUDA library issues
        # GPU can be enabled later by changing device to "cuda"
        return WhisperModel(self.config.whisper_model, device="cpu", compute_type="int8")

    def transcribe(self, audio_path: str) -> str:
        """
        Transcribe audio file to text.

        Args:
            audio_path: Path to audio file

        Returns:
            Transcribed text
        """
        if self.config.whisper_provider == 'local':
            return self._transcribe_local(audio_path)
        else:
            return self._transcribe_openai(audio_path)

    def _transcribe_local(self, audio_path: str) -> str:
        """Transcribe using local faster-whisper."""
        # Lazy load model if not preloaded
        if self._local_model is None:
            print(f"[Loading Whisper model: {self.config.whisper_model}]")
            self._local_model = self._load_whisper_model()

        print("[Transcribing...]")
        segments, info = self._local_model.transcribe(audio_path, beam_size=5)

        # Combine all segments
        text = " ".join(segment.text.strip() for segment in segments)
        return text

    def _transcribe_openai(self, audio_path: str) -> str:
        """Transcribe using OpenAI Whisper API."""
        if not OPENAI_AVAILABLE:
            raise ImportError("openai package not installed. Run: pip install openai")

        api_key = self.config.openai_api_key
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")

        # Get audio duration for cost tracking
        with wave.open(audio_path, 'rb') as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            duration = frames / float(rate)

        client = OpenAI(api_key=api_key)

        print("[Transcribing via OpenAI...]")
        with open(audio_path, 'rb') as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )

        # Track cost
        track_whisper_usage(duration)

        return transcript.text


class VoiceInput:
    """
    Combined voice recording and transcription.

    Usage:
        voice = VoiceInput()
        voice.start_recording()
        # ... wait for user to finish speaking ...
        text = voice.stop_and_transcribe()
    """

    def __init__(self, config: Optional[Config] = None):
        """Initialize voice input."""
        self.config = config or default_config
        self.recorder = VoiceRecorder(config)
        self.transcriber = Transcriber(config)
        self._current_audio_path = None

    def preload_model(self):
        """Pre-load the Whisper model at startup."""
        self.transcriber.preload_model()

    def start_recording(self):
        """Start recording audio."""
        self.recorder.start_recording()

    def stop_and_transcribe(self, min_duration: float = 1.0) -> str:
        """
        Stop recording and transcribe.

        Args:
            min_duration: Minimum recording duration in seconds

        Returns:
            Transcribed text, or empty string if recording was too short
        """
        audio_path = self.recorder.stop_recording(min_duration=min_duration)

        if audio_path is None:
            return ""

        self._current_audio_path = audio_path

        try:
            text = self.transcriber.transcribe(audio_path)
            print(f"[Transcribed: {text}]")
            return text
        finally:
            # Clean up temp file
            if os.path.exists(audio_path):
                os.remove(audio_path)

    def cleanup(self):
        """Clean up resources."""
        self.recorder.cleanup()


class HandsFreeVoiceInput:
    """
    Hands-free voice input with wake word detection and VAD.

    Listens for wake word, then records until silence is detected.
    Trims silence from audio before transcription.
    """

    def __init__(self, config: Optional[Config] = None, led_callback=None,
                 on_recording_start=None, on_recording_stop=None):
        """
        Initialize hands-free voice input.

        Args:
            config: Configuration object
            led_callback: Function to call for LED control (on=True, off=False)
            on_recording_start: Callback when recording begins (e.g., printer.double_chirp)
            on_recording_stop: Callback when recording ends (e.g., printer.long_chirp)
        """
        self.config = config or default_config
        self._device_rate = _get_device_sample_rate()
        self.transcriber = Transcriber(config)
        self._running = False
        self._led_callback = led_callback
        self._on_recording_start = on_recording_start
        self._on_recording_stop = on_recording_stop

        # VAD for detecting speech end (always at 16kHz - we resample)
        if VAD_AVAILABLE:
            self._vad = VoiceActivityDetector(
                sample_rate=16000,
                aggressiveness=3
            )
        else:
            self._vad = None
            print("[Warning: VAD not available, using time-based recording]")

        # Spontaneous wake event
        self._spontaneous_event = threading.Event()

        # Wake word detector (lazy loaded)
        self._wake_detector = None

    def _set_led(self, on: bool):
        """Control LED indicator."""
        if self._led_callback:
            try:
                self._led_callback(on)
            except Exception as e:
                print(f"[LED error: {e}]")

    def preload_models(self):
        """Pre-load all models."""
        self.transcriber.preload_model()

        # Load wake word detector
        try:
            from .wakeword import WakeWordDetector
            self._wake_detector = WakeWordDetector(self.config)
            self._wake_detector.load_model()
        except ImportError as e:
            print(f"[Warning: Wake word detection not available: {e}]")
            print("[Install with: pip install pvporcupine]")
        except ValueError as e:
            print(f"[Wake word error: {e}]")

    def trigger_spontaneous(self):
        """Trigger a spontaneous wake, interrupting listen_for_wake_word."""
        self._spontaneous_event.set()

    def listen_for_wake_word(self, timeout: float = None) -> str:
        """
        Listen for wake word or spontaneous wake event.

        Args:
            timeout: Maximum time to listen (None = forever)

        Returns:
            "wake_word" if wake word detected,
            "spontaneous" if spontaneous event fired,
            "" if timeout or cancelled
        """
        self._spontaneous_event.clear()

        if self._wake_detector is None:
            print("[Wake word not available, press Enter to activate]")
            try:
                import select
                import sys
                if timeout:
                    ready, _, _ = select.select([sys.stdin], [], [], timeout)
                    if not ready:
                        if self._spontaneous_event.is_set():
                            return "spontaneous"
                        return ""
                    return "wake_word"
                else:
                    # Poll stdin and spontaneous event
                    while self._running and not self._spontaneous_event.is_set():
                        ready, _, _ = select.select([sys.stdin], [], [], 0.5)
                        if ready:
                            sys.stdin.readline()
                            return "wake_word"
                    if self._spontaneous_event.is_set():
                        return "spontaneous"
                    return ""
            except:
                return ""

        import queue
        import time

        frame_length = self._wake_detector.frame_length  # 512 samples at 16kHz
        # How many native-rate samples correspond to one Porcupine frame
        native_frame_length = int(frame_length * self._device_rate / 16000)
        audio_queue = queue.Queue()
        frame_buffer = []

        def audio_callback(indata, frames, time_info, status):
            audio_queue.put(bytes(indata))

        stream = sd.RawInputStream(
            samplerate=self._device_rate,
            channels=1,
            dtype='int16',
            blocksize=native_frame_length,
            callback=audio_callback
        )
        stream.start()

        start_time = time.time()
        detected = False

        print(f"[Listening for '{self._wake_detector.keyword}' at {self._device_rate}Hz...]")

        try:
            while self._running and not self._spontaneous_event.is_set():
                if timeout and (time.time() - start_time) > timeout:
                    break

                try:
                    audio_data = audio_queue.get(timeout=0.1)
                    audio_chunk = np.frombuffer(audio_data, dtype=np.int16)
                    frame_buffer.extend(audio_chunk.tolist())

                    # Process when we have enough native-rate samples for one 16kHz frame
                    while len(frame_buffer) >= native_frame_length:
                        native_frame = np.array(frame_buffer[:native_frame_length], dtype=np.int16)
                        frame_buffer = frame_buffer[native_frame_length:]

                        # Resample to 16kHz for Porcupine
                        frame_16k = _resample(native_frame, self._device_rate, 16000)
                        # Ensure exact frame_length
                        if len(frame_16k) > frame_length:
                            frame_16k = frame_16k[:frame_length]
                        elif len(frame_16k) < frame_length:
                            frame_16k = np.pad(frame_16k, (0, frame_length - len(frame_16k)))

                        amplitude = max(abs(int(native_frame.min())), abs(int(native_frame.max())))
                        print(f"[amp: {amplitude:5d}]", end='\r')

                        if self._wake_detector.process(frame_16k.tolist()):
                            print(f"\n[Wake word detected: '{self._wake_detector.keyword}'!]")
                            detected = True
                            break

                    if detected:
                        break

                except queue.Empty:
                    continue

        finally:
            stream.stop()
            stream.close()

        if self._spontaneous_event.is_set():
            self._spontaneous_event.clear()
            return "spontaneous"
        return "wake_word" if detected else ""

    def record_until_silence(
        self,
        max_duration: float = 30.0,
        silence_duration: float = 1.5,
        initial_wait: float = 5.0,
        min_speech_duration: float = 0.5
    ) -> Optional[str]:
        """
        Record audio until silence is detected.

        Args:
            max_duration: Maximum recording duration in seconds
            silence_duration: How long silence must last to stop (seconds)
            min_speech_duration: Minimum speech duration to accept

        Returns:
            Path to audio file, or None if no speech
        """
        self._set_led(True)

        # Frame settings for VAD (30ms frames at 16kHz for VAD processing)
        import queue
        import time

        frame_duration_ms = 30
        # Record at native rate, but calculate frame size for VAD at 16kHz
        vad_frame_size = int(16000 * frame_duration_ms / 1000)  # 480 samples at 16kHz
        native_frame_size = int(self._device_rate * frame_duration_ms / 1000)

        audio_queue = queue.Queue()

        def audio_callback(indata, frames_count, time_info, status):
            audio_queue.put(bytes(indata))

        stream = sd.RawInputStream(
            samplerate=self._device_rate,
            channels=1,
            dtype='int16',
            blocksize=native_frame_size,
            callback=audio_callback
        )
        stream.start()

        frames = []
        speech_frames = 0
        silence_frames = 0
        silence_threshold = int(silence_duration * 1000 / frame_duration_ms)
        started_speaking = False

        start_time = time.time()
        print(f"[Recording at {self._device_rate}Hz... (speak now)]")

        # Signal recording started
        if self._on_recording_start:
            try:
                self._on_recording_start()
            except Exception as e:
                print(f"[Recording start callback error: {e}]")

        try:
            while self._running:
                # Check max duration
                elapsed = time.time() - start_time
                if elapsed > max_duration:
                    print(f"[Max duration reached ({max_duration}s)]")
                    break

                # Read audio frame (non-blocking with timeout)
                try:
                    audio_bytes = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                frames.append(audio_bytes)

                # Resample to 16kHz for VAD
                native_audio = np.frombuffer(audio_bytes, dtype=np.int16)
                audio_16k = _resample(native_audio, self._device_rate, 16000)
                audio_16k_bytes = audio_16k.tobytes()

                # Check for speech using VAD
                if self._vad:
                    # Ensure correct frame size for VAD
                    expected_bytes = vad_frame_size * 2
                    if len(audio_16k_bytes) >= expected_bytes:
                        is_speech = self._vad.is_speech(audio_16k_bytes[:expected_bytes])
                    else:
                        is_speech = False
                else:
                    # Fallback: use simple energy detection
                    energy = np.sqrt(np.mean(native_audio.astype(np.float32) ** 2))
                    is_speech = energy > 500  # Threshold

                if is_speech:
                    speech_frames += 1
                    silence_frames = 0
                    if not started_speaking:
                        started_speaking = True
                        print("[Speech detected]")
                    elif silence_frames > 0:
                        # Was counting silence but VAD triggered again
                        print(f"[VAD re-triggered after {silence_frames} silent frames]", end='\r')
                else:
                    if started_speaking and silence_frames == 0:
                        print("[Silence started...]")
                    silence_frames += 1
                    if started_speaking:
                        print(f"[silence: {silence_frames}/{silence_threshold}]", end='\r')

                # Before speech: give up after initial_wait seconds of total silence
                if not started_speaking:
                    initial_wait_frames = int(initial_wait * 1000 / frame_duration_ms)
                    if silence_frames >= initial_wait_frames:
                        print(f"\n[No speech detected after {initial_wait}s, cancelling]")
                        break
                # After speech: stop after silence_duration seconds of silence
                elif silence_frames >= silence_threshold:
                    print(f"\n[Silence detected, stopping]")
                    break

        finally:
            stream.stop()
            stream.close()
            self._set_led(False)

            # Signal recording stopped
            if self._on_recording_stop:
                try:
                    self._on_recording_stop()
                except Exception as e:
                    print(f"[Recording stop callback error: {e}]")

        # Check minimum speech
        speech_duration = speech_frames * frame_duration_ms / 1000
        if speech_duration < min_speech_duration:
            print(f"[Too little speech ({speech_duration:.1f}s), cancelled]")
            return None

        # Combine frames and resample to 16kHz
        raw_audio = np.frombuffer(b''.join(frames), dtype=np.int16)
        audio_16k = _resample(raw_audio, self._device_rate, 16000)
        audio_data = audio_16k.tobytes()

        if VAD_AVAILABLE:
            audio_data = trim_silence(audio_data, 16000)

        # Save to temp file
        temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        temp_path = temp_file.name
        temp_file.close()

        with wave.open(temp_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio_data)

        duration = len(audio_data) / 2 / 16000
        print(f"[Recorded {duration:.1f}s of audio]")

        return temp_path

    def listen_and_transcribe(self) -> tuple:
        """
        Full hands-free flow: wait for wake word, record, transcribe.

        Returns:
            (text, wake_type) where wake_type is "wake_word", "spontaneous", or ""
            text is None if cancelled/failed or if spontaneous
        """
        # Wait for wake word or spontaneous event
        wake_type = self.listen_for_wake_word()
        if not wake_type:
            return None, ""
        if wake_type == "spontaneous":
            return None, "spontaneous"

        # Record until silence
        audio_path = self.record_until_silence()
        if audio_path is None:
            return None, "wake_word"

        # Transcribe
        try:
            text = self.transcriber.transcribe(audio_path)
            print(f"[Transcribed: {text}]")
            return text, "wake_word"
        finally:
            if os.path.exists(audio_path):
                os.remove(audio_path)

    def start(self):
        """Start the hands-free listener."""
        self._running = True

    def stop(self):
        """Stop the hands-free listener."""
        self._running = False

    def cleanup(self):
        """Clean up resources."""
        self._running = False


def test_voice():
    """Test voice recording and transcription."""
    import time

    voice = VoiceInput()

    print("Starting 3 second recording test...")
    voice.start_recording()
    time.sleep(3)
    text = voice.stop_and_transcribe()

    print(f"\nTranscribed text: {text}")
    voice.cleanup()


if __name__ == '__main__':
    test_voice()