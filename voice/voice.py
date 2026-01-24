"""
Voice recording and transcription for the Receipt library.
Supports local Whisper (faster-whisper) and OpenAI Whisper API.
"""

import os
import sys
import tempfile
import wave
from typing import Optional

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

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
        self._stream = None
        self._frames = []
        self._recording = False

    def start_recording(self):
        """Start recording audio."""
        self._frames = []
        self._recording = True

        self._stream = sd.RawInputStream(
            samplerate=self.config.sample_rate,
            channels=1,
            dtype='int16',
            blocksize=1024,
            callback=self._audio_callback
        )
        self._stream.start()
        print("[Recording...]")

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

        # Calculate duration: frames * buffer_size / sample_rate
        duration = len(self._frames) * 1024 / self.config.sample_rate

        if duration < min_duration:
            print(f"[Recording too short ({duration:.1f}s < {min_duration}s), cancelled]")
            self._frames = []
            return None

        print(f"[Recording stopped ({duration:.1f}s)]")

        # Save to temporary WAV file
        temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        temp_path = temp_file.name
        temp_file.close()

        with wave.open(temp_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.config.sample_rate)
            wf.writeframes(b''.join(self._frames))

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
        self.transcriber = Transcriber(config)
        self._running = False
        self._led_callback = led_callback
        self._on_recording_start = on_recording_start
        self._on_recording_stop = on_recording_stop

        # VAD for detecting speech end
        if VAD_AVAILABLE:
            self._vad = VoiceActivityDetector(
                sample_rate=self.config.sample_rate,
                aggressiveness=2
            )
        else:
            self._vad = None
            print("[Warning: VAD not available, using time-based recording]")

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
        except ImportError:
            print("[Warning: Wake word detection not available]")
            print("[Install with: pip install openwakeword]")

    def listen_for_wake_word(self, timeout: float = None) -> bool:
        """
        Listen for wake word.

        Args:
            timeout: Maximum time to listen (None = forever)

        Returns:
            True if wake word detected, False if timeout
        """
        if self._wake_detector is None:
            print("[Wake word not available, press Enter to activate]")
            try:
                import select
                import sys
                if timeout:
                    ready, _, _ = select.select([sys.stdin], [], [], timeout)
                    return bool(ready)
                else:
                    input()
                    return True
            except:
                return False

        # Open stream for wake word detection
        chunk_size = 1280  # ~80ms at 16kHz
        stream = sd.RawInputStream(
            samplerate=self.config.sample_rate,
            channels=1,
            dtype='int16',
            blocksize=chunk_size
        )
        stream.start()

        import time

        start_time = time.time()
        detected = False

        print("[Listening for wake word...]")

        try:
            while self._running or timeout is None:
                if timeout and (time.time() - start_time) > timeout:
                    break

                audio_data, overflowed = stream.read(chunk_size)
                audio_chunk = np.frombuffer(audio_data, dtype=np.int16)

                if self._wake_detector.detect(audio_chunk, threshold=0.5):
                    print("[Wake word detected!]")
                    detected = True
                    self._wake_detector.reset()
                    break

        finally:
            stream.stop()
            stream.close()

        return detected

    def record_until_silence(
        self,
        max_duration: float = 30.0,
        silence_duration: float = 2.0,
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

        # Frame settings for VAD (30ms frames)
        frame_duration_ms = 30
        frame_size = int(self.config.sample_rate * frame_duration_ms / 1000)

        stream = sd.RawInputStream(
            samplerate=self.config.sample_rate,
            channels=1,
            dtype='int16',
            blocksize=frame_size
        )
        stream.start()

        import time

        frames = []
        speech_frames = 0
        silence_frames = 0
        silence_threshold = int(silence_duration * 1000 / frame_duration_ms)
        started_speaking = False

        start_time = time.time()
        print("[Recording... (speak now)]")

        # Signal recording started
        if self._on_recording_start:
            try:
                self._on_recording_start()
            except Exception as e:
                print(f"[Recording start callback error: {e}]")

        try:
            while True:
                # Check max duration
                elapsed = time.time() - start_time
                if elapsed > max_duration:
                    print(f"[Max duration reached ({max_duration}s)]")
                    break

                # Read audio frame
                audio_data, overflowed = stream.read(frame_size)
                audio_bytes = bytes(audio_data)
                frames.append(audio_bytes)

                # Check for speech using VAD
                if self._vad:
                    is_speech = self._vad.is_speech(audio_bytes)
                else:
                    # Fallback: use simple energy detection
                    audio = np.frombuffer(audio_bytes, dtype=np.int16)
                    energy = np.sqrt(np.mean(audio.astype(np.float32) ** 2))
                    is_speech = energy > 500  # Threshold

                if is_speech:
                    speech_frames += 1
                    silence_frames = 0
                    if not started_speaking:
                        started_speaking = True
                        print("[Speech detected]")
                else:
                    if started_speaking:
                        silence_frames += 1

                # Stop if enough silence after speech
                if started_speaking and silence_frames >= silence_threshold:
                    print(f"[Silence detected, stopping]")
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

        # Combine frames and trim silence
        audio_data = b''.join(frames)

        if VAD_AVAILABLE:
            audio_data = trim_silence(audio_data, self.config.sample_rate)

        # Save to temp file
        temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        temp_path = temp_file.name
        temp_file.close()

        with wave.open(temp_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.config.sample_rate)
            wf.writeframes(audio_data)

        duration = len(audio_data) / 2 / self.config.sample_rate
        print(f"[Recorded {duration:.1f}s of audio]")

        return temp_path

    def listen_and_transcribe(self) -> Optional[str]:
        """
        Full hands-free flow: wait for wake word, record, transcribe.

        Returns:
            Transcribed text, or None if cancelled/failed
        """
        # Wait for wake word
        if not self.listen_for_wake_word():
            return None

        # Record until silence
        audio_path = self.record_until_silence()
        if audio_path is None:
            return None

        # Transcribe
        try:
            text = self.transcriber.transcribe(audio_path)
            print(f"[Transcribed: {text}]")
            return text
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