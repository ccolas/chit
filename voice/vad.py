"""
Voice Activity Detection (VAD) for detecting speech and silence.
Uses webrtcvad for lightweight, Raspberry Pi-friendly detection.
"""

import collections
import numpy as np
from typing import Optional, Tuple

try:
    import webrtcvad
    WEBRTCVAD_AVAILABLE = True
except ImportError:
    WEBRTCVAD_AVAILABLE = False


class VoiceActivityDetector:
    """
    Detects voice activity in audio streams.

    Uses webrtcvad which is lightweight and works well on Raspberry Pi.
    """

    def __init__(self, sample_rate: int = 16000, aggressiveness: int = 2):
        """
        Initialize VAD.

        Args:
            sample_rate: Audio sample rate (must be 8000, 16000, 32000, or 48000)
            aggressiveness: VAD aggressiveness (0-3, higher = more aggressive filtering)
        """
        if not WEBRTCVAD_AVAILABLE:
            raise ImportError("webrtcvad not installed. Run: pip install webrtcvad")

        self.sample_rate = sample_rate
        self.vad = webrtcvad.Vad(aggressiveness)

        # Frame duration must be 10, 20, or 30 ms
        self.frame_duration_ms = 30
        self.frame_size = int(sample_rate * self.frame_duration_ms / 1000)

    def is_speech(self, audio_chunk: bytes) -> bool:
        """
        Check if audio chunk contains speech.

        Args:
            audio_chunk: Raw audio bytes (16-bit PCM)

        Returns:
            True if speech detected
        """
        # Ensure chunk is correct size
        expected_bytes = self.frame_size * 2  # 16-bit = 2 bytes per sample
        if len(audio_chunk) != expected_bytes:
            return False

        return self.vad.is_speech(audio_chunk, self.sample_rate)

    def detect_speech_end(
        self,
        audio_frames: list,
        min_silence_duration_ms: int = 800,
        speech_threshold: float = 0.5
    ) -> bool:
        """
        Detect if speech has ended (sufficient silence after speech).

        Args:
            audio_frames: List of audio frame bytes
            min_silence_duration_ms: Minimum silence to consider speech ended
            speech_threshold: Ratio of speech frames to consider as "speaking"

        Returns:
            True if speech has ended
        """
        if not audio_frames:
            return False

        # Calculate how many frames of silence we need
        frames_needed = int(min_silence_duration_ms / self.frame_duration_ms)

        # Check if last N frames are silence
        if len(audio_frames) < frames_needed:
            return False

        recent_frames = audio_frames[-frames_needed:]
        speech_count = sum(1 for f in recent_frames if self.is_speech(f))

        # If very little speech in recent frames, consider it ended
        return speech_count < len(recent_frames) * (1 - speech_threshold)


def trim_silence(
    audio_data: bytes,
    sample_rate: int = 16000,
    threshold_db: float = -40,
    min_silence_ms: int = 100
) -> bytes:
    """
    Trim silence from beginning and end of audio.

    Args:
        audio_data: Raw audio bytes (16-bit PCM)
        sample_rate: Audio sample rate
        threshold_db: Volume threshold in dB (below this is silence)
        min_silence_ms: Minimum silence duration to trim

    Returns:
        Trimmed audio bytes
    """
    # Convert to numpy array
    audio = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)

    if len(audio) == 0:
        return audio_data

    # Calculate frame size
    frame_size = int(sample_rate * min_silence_ms / 1000)

    # Convert threshold to amplitude
    threshold = 10 ** (threshold_db / 20) * 32768

    # Find start (first frame above threshold)
    start_idx = 0
    for i in range(0, len(audio) - frame_size, frame_size):
        frame = audio[i:i + frame_size]
        if np.max(np.abs(frame)) > threshold:
            start_idx = max(0, i - frame_size)  # Include a bit before
            break

    # Find end (last frame above threshold)
    end_idx = len(audio)
    for i in range(len(audio) - frame_size, frame_size, -frame_size):
        frame = audio[i:i + frame_size]
        if np.max(np.abs(frame)) > threshold:
            end_idx = min(len(audio), i + frame_size * 2)  # Include a bit after
            break

    # Convert back to bytes
    trimmed = audio[start_idx:end_idx].astype(np.int16)
    return trimmed.tobytes()


def get_audio_energy(audio_chunk: bytes) -> float:
    """
    Calculate RMS energy of audio chunk.

    Args:
        audio_chunk: Raw audio bytes (16-bit PCM)

    Returns:
        RMS energy (0-1 scale)
    """
    audio = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32)
    if len(audio) == 0:
        return 0.0

    rms = np.sqrt(np.mean(audio ** 2))
    # Normalize to 0-1 range (32768 is max for int16)
    return min(1.0, rms / 32768)