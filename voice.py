"""
Voice recording and transcription for the Receipt library.
Supports local Whisper (faster-whisper) and OpenAI Whisper API.
"""

import os
import sys
import tempfile
import wave
from contextlib import contextmanager
from typing import Optional

@contextmanager
def _suppress_alsa_errors():
    """Suppress ALSA error messages during PyAudio init."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    os.dup2(devnull, 2)
    os.close(devnull)
    try:
        yield
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)

with _suppress_alsa_errors():
    import pyaudio
from faster_whisper import WhisperModel

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from .config import Config, default_config
except:
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
        self._audio = None
        self._stream = None
        self._frames = []
        self._recording = False

    def _init_audio(self):
        """Initialize PyAudio."""
        if self._audio is None:
            with _suppress_alsa_errors():
                self._audio = pyaudio.PyAudio()

    def start_recording(self):
        """Start recording audio."""
        self._init_audio()
        self._frames = []
        self._recording = True

        self._stream = self._audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.config.sample_rate,
            input=True,
            frames_per_buffer=1024,
            stream_callback=self._audio_callback
        )
        self._stream.start_stream()
        print("[Recording...]")

    def _audio_callback(self, in_data, frame_count, time_info, status):
        """Callback for audio stream."""
        if self._recording:
            self._frames.append(in_data)
        return (in_data, pyaudio.paContinue)

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
            self._stream.stop_stream()
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
        if self._audio:
            self._audio.terminate()
            self._audio = None


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

        client = OpenAI(api_key=api_key)

        print("[Transcribing via OpenAI...]")
        with open(audio_path, 'rb') as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
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