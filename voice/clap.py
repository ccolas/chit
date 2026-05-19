"""
Double-clap detection as a fallback when Picovoice is unavailable.
Drop-in replacement for WakeWordDetector: same interface, no external service.
"""

import os
import time
from typing import Optional

try:
    from ..config import Config, default_config
except ImportError:
    from config import Config, default_config


class ClapDetector:
    """
    Detects double-claps via raw audio amplitude.

    Two amplitude spikes within [MIN_GAP, MAX_GAP] count as a trigger.
    Tunable via env vars: CLAP_MIN_AMPLITUDE, CLAP_SPIKE_RATIO,
    CLAP_MIN_GAP_MS, CLAP_MAX_GAP_MS, CLAP_DEBOUNCE_MS.
    """

    keyword = "double clap"

    def __init__(self, config: Optional[Config] = None):
        self.config = config or default_config

        self._min_amp = int(os.environ.get('CLAP_MIN_AMPLITUDE', 8000))
        self._spike_ratio = float(os.environ.get('CLAP_SPIKE_RATIO', 6.0))
        self._min_gap = float(os.environ.get('CLAP_MIN_GAP_MS', 120)) / 1000.0
        self._max_gap = float(os.environ.get('CLAP_MAX_GAP_MS', 700)) / 1000.0
        self._debounce = float(os.environ.get('CLAP_DEBOUNCE_MS', 1500)) / 1000.0

        self._baseline = 500.0
        self._first_clap_time = None
        self._last_detect_time = 0.0

    @property
    def sample_rate(self) -> int:
        return 16000

    @property
    def frame_length(self) -> int:
        return 512  # ~32ms at 16kHz, matches Porcupine's default frame size

    def load_model(self):
        print(f"[Clap detector ready - double-clap to activate]")
        print(f"[min_amp={self._min_amp} spike_ratio={self._spike_ratio:.1f} "
              f"gap={int(self._min_gap*1000)}-{int(self._max_gap*1000)}ms]")

    def process(self, audio_frame: list) -> bool:
        peak = max(abs(s) for s in audio_frame) if audio_frame else 0
        now = time.monotonic()

        if now - self._last_detect_time < self._debounce:
            self._baseline = 0.98 * self._baseline + 0.02 * peak
            return False

        is_spike = peak > self._min_amp and peak > self._baseline * self._spike_ratio

        if is_spike:
            if self._first_clap_time is None:
                self._first_clap_time = now
            else:
                gap = now - self._first_clap_time
                if self._min_gap <= gap <= self._max_gap:
                    self._first_clap_time = None
                    self._last_detect_time = now
                    return True
                elif gap > self._max_gap:
                    self._first_clap_time = now
        else:
            if self._first_clap_time is not None and (now - self._first_clap_time) > self._max_gap:
                self._first_clap_time = None
            self._baseline = 0.95 * self._baseline + 0.05 * peak

        return False

    def cleanup(self):
        pass
