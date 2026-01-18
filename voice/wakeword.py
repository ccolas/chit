"""
Wake word detection for hands-free activation.
Uses OpenWakeWord for free, open-source wake word detection.
"""

import numpy as np
from typing import Callable, Optional
import threading
import time

try:
    from openwakeword.model import Model as OWWModel
    OPENWAKEWORD_AVAILABLE = True
except ImportError:
    OPENWAKEWORD_AVAILABLE = False

try:
    from ..config import Config, default_config
except ImportError:
    from config import Config, default_config


class WakeWordDetector:
    """
    Detects wake words using OpenWakeWord.

    Supports built-in models like "hey_jarvis" or custom trained models.
    """

    # Built-in wake words - "hey_jarvis" sounds closest to "hey chit"
    DEFAULT_MODEL = "hey_jarvis"

    # Custom model path (if trained)
    CUSTOM_MODEL_PATH = "models/hey_chit.onnx"

    def __init__(self, config: Optional[Config] = None, model_name: str = None):
        """
        Initialize wake word detector.

        Args:
            config: Configuration object
            model_name: Wake word model to use (default: checks for custom hey_chit first)
        """
        if not OPENWAKEWORD_AVAILABLE:
            raise ImportError(
                "openwakeword not installed. Run: pip install openwakeword"
            )

        self.config = config or default_config

        # Auto-detect custom model if it exists
        if model_name is None:
            import os
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            custom_path = os.path.join(base_dir, self.CUSTOM_MODEL_PATH)
            if os.path.exists(custom_path):
                self.model_name = custom_path
                print(f"[Using custom wake word: {custom_path}]")
            else:
                self.model_name = self.DEFAULT_MODEL
        else:
            self.model_name = model_name

        self._model = None
        self._running = False
        self._callback = None
        self._thread = None

    def load_model(self):
        """Load the wake word model."""
        if self._model is None:
            print(f"[Loading wake word model: {self.model_name}]")
            self._model = OWWModel(
                wakeword_models=[self.model_name],
                inference_framework="onnx"
            )
            print("[Wake word model loaded]")

    def detect(self, audio_chunk: np.ndarray, threshold: float = 0.5) -> bool:
        """
        Check if wake word is in audio chunk.

        Args:
            audio_chunk: Audio samples (16kHz, int16 or float32)
            threshold: Detection threshold (0-1)

        Returns:
            True if wake word detected
        """
        if self._model is None:
            self.load_model()

        # Convert to float32 if needed
        if audio_chunk.dtype == np.int16:
            audio_chunk = audio_chunk.astype(np.float32) / 32768.0

        # Run prediction
        prediction = self._model.predict(audio_chunk)

        # Check if any wake word scores exceed threshold
        for model_name, score in prediction.items():
            if score > threshold:
                return True

        return False

    def reset(self):
        """Reset the model state between detections."""
        if self._model:
            self._model.reset()