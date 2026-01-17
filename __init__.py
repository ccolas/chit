"""
Receipt - Voice-to-Print Assistant

A library for building voice-controlled thermal printer assistants.
Record voice -> Transcribe with Whisper -> Query LLM -> Print response.

Usage:
    # Run in laptop mode (keyboard input)
    python -m receipt --backend laptop

    # Run in Raspberry Pi mode (GPIO buttons)
    python -m receipt --backend raspberry

    # Use different LLM
    python -m receipt --model gpt-4o

    # Use OpenAI Whisper API instead of local
    python -m receipt --whisper openai
"""

from .config import Config
from .llm import LLMClient
from .printer import ReceiptPrinter
from .voice import VoiceInput, VoiceRecorder, Transcriber
from .main import ReceiptAssistant, main

__version__ = "0.1.0"
__all__ = [
    "Config",
    "LLMClient",
    "ReceiptPrinter",
    "VoiceInput",
    "VoiceRecorder",
    "Transcriber",
    "ReceiptAssistant",
    "main",
]