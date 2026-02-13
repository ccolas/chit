"""
Wake word detection using Picovoice Porcupine.
Runs 100% on-device - no audio sent to cloud.
"""

import os
import platform
import glob
from typing import Optional

try:
    import pvporcupine
    PORCUPINE_AVAILABLE = True
except ImportError:
    PORCUPINE_AVAILABLE = False

try:
    from ..config import Config, default_config
except ImportError:
    from config import Config, default_config


def _load_access_key() -> Optional[str]:
    """Load Picovoice access key from file."""
    repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    key_file = os.path.join(repo_path, '.picovoice_key')
    if os.path.exists(key_file):
        with open(key_file) as f:
            return f.read().strip()
    return os.environ.get('PICOVOICE_ACCESS_KEY')


def _is_raspberry_pi() -> bool:
    """Check if running on Raspberry Pi."""
    if platform.system() != 'Linux':
        return False
    try:
        with open('/proc/cpuinfo', 'r') as f:
            return 'Raspberry Pi' in f.read() or 'BCM' in f.read()
    except:
        return False


def _find_custom_model() -> Optional[str]:
    """Find custom .ppn model for current platform."""
    voice_dir = os.path.dirname(os.path.abspath(__file__))

    if _is_raspberry_pi():
        # Look for Raspberry Pi model
        patterns = ['*raspberry-pi*.ppn', '*raspberry*.ppn', '*rpi*.ppn']
    elif platform.system() == 'Darwin':
        # macOS - check architecture
        if platform.machine() == 'arm64':
            patterns = ['*mac*arm64*.ppn', '*macos*arm*.ppn']
        else:
            patterns = ['*mac*x86*.ppn', '*macos*intel*.ppn']
    else:
        # Linux
        patterns = ['*linux*.ppn']

    for pattern in patterns:
        matches = glob.glob(os.path.join(voice_dir, pattern))
        if matches:
            return matches[0]

    return None


class WakeWordDetector:
    """
    Detects wake words using Picovoice Porcupine.

    On Raspberry Pi: uses custom "hey chit" model if available
    On Mac/other: uses built-in "jarvis" keyword
    """

    # Default built-in wake word (used when no custom model)
    DEFAULT_KEYWORD = "jarvis"

    # All available built-in keywords
    AVAILABLE_KEYWORDS = list(pvporcupine.KEYWORDS) if PORCUPINE_AVAILABLE else []

    def __init__(self, config: Optional[Config] = None, keyword: str = None):
        """
        Initialize wake word detector.

        Args:
            config: Configuration object
            keyword: Wake word to detect (default: auto-detect)
        """
        if not PORCUPINE_AVAILABLE:
            raise ImportError(
                "pvporcupine not installed. Run: pip install pvporcupine"
            )

        self.config = config or default_config
        self._custom_model_path = _find_custom_model()

        if self._custom_model_path:
            # Use custom model - extract name from filename
            basename = os.path.basename(self._custom_model_path)
            self.keyword = basename.split('_')[0].replace('-', ' ')
            print(f"[Using custom wake word model: {basename}]")
        else:
            # Use built-in keyword
            self.keyword = keyword or self.DEFAULT_KEYWORD
            if self.keyword not in pvporcupine.KEYWORDS:
                raise ValueError(
                    f"Unknown keyword '{self.keyword}'. "
                    f"Available: {list(pvporcupine.KEYWORDS)}"
                )

        self._access_key = _load_access_key()
        if not self._access_key:
            raise ValueError(
                "Picovoice access key not found!\n"
                "Get a FREE key from: https://console.picovoice.ai/\n"
                "Then save it to .picovoice_key or set PICOVOICE_ACCESS_KEY"
            )

        self._porcupine = None

    @property
    def sample_rate(self) -> int:
        """Required sample rate (16000 Hz)."""
        return 16000

    @property
    def frame_length(self) -> int:
        """Required frame length in samples."""
        if self._porcupine:
            return self._porcupine.frame_length
        return 512  # Default for Porcupine

    def load_model(self):
        """Load the Porcupine model."""
        if self._porcupine is None:
            print(f"[Loading wake word: '{self.keyword}']")

            if self._custom_model_path:
                # Use custom .ppn model
                self._porcupine = pvporcupine.create(
                    access_key=self._access_key,
                    keyword_paths=[self._custom_model_path]
                )
            else:
                # Use built-in keyword
                self._porcupine = pvporcupine.create(
                    access_key=self._access_key,
                    keywords=[self.keyword]
                )

            print(f"[Wake word ready - say '{self.keyword}' to activate]")

    def process(self, audio_frame: list) -> bool:
        """
        Process audio frame and check for wake word.

        Args:
            audio_frame: List of int16 audio samples (must be frame_length samples)

        Returns:
            True if wake word detected
        """
        if self._porcupine is None:
            self.load_model()

        result = self._porcupine.process(audio_frame)
        return result >= 0

    def cleanup(self):
        """Release resources."""
        if self._porcupine:
            self._porcupine.delete()
            self._porcupine = None