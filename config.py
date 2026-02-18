"""
Configuration for the Receipt library.
Voice-to-print assistant using Whisper + LLM + thermal printer.
"""

import os
from dataclasses import dataclass, field
from typing import Literal, Optional

REPO_PATH = os.path.dirname(__file__)


def _load_api_key(filename: str) -> Optional[str]:
    """Load API key from a local file in the repo."""
    path = os.path.join(REPO_PATH, filename)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return f.read().strip()
    return None


@dataclass
class Config:
    """Configuration for the receipt system."""

    # LLM settings
    llm_provider: Literal['openrouter', 'openai'] = 'openrouter'
    llm_model: str = 'anthropic/claude-haiku-4.5'
    openrouter_api_key: Optional[str] = field(default_factory=lambda: _load_api_key('.api_openrouter') or os.environ.get('OPENROUTER_API_KEY'))
    openai_api_key: Optional[str] = field(default_factory=lambda: _load_api_key('.api_openai') or os.environ.get('OPENAI_API_KEY'))

    # Whisper settings
    whisper_provider: Literal['local', 'openai'] = 'local'  # 'local' uses faster-whisper
    whisper_model: str = 'medium'  # base, small, medium, large

    # Printer settings
    printer_vendor_id: int = 0x0416
    printer_product_id: int = 0x5011
    printer_width: int = 384  # pixels for 58mm paper
    printer_char_width: int = 40  # characters per line

    # Audio settings
    sample_rate: int = 16000

    # Conversation
    conv_name: str = 'default'

    # Conversation settings
    max_context_messages: int = 50  # Only send last N messages to LLM (sliding window)
    conversation_dir: str = field(default_factory=lambda: os.path.join(REPO_PATH, 'conversations'))

    # Font settings
    font_dir: str = field(default_factory=lambda: os.path.join(REPO_PATH, 'fonts'))
    font_title_size: int = 34
    font_heading_size: int = 24
    font_normal_size: int = 22
    font_small_size: int = 18

    # System prompt location
    prompts_dir: str = field(default_factory=lambda: os.path.join(os.path.dirname(__file__), 'llm'))

    def __post_init__(self):
        """Ensure directories exist."""
        os.makedirs(self.conversation_dir, exist_ok=True)

    def get_system_prompt(self) -> str:
        """Load the system prompt from file, plus optional personal prompt."""
        prompt_path = os.path.join(self.prompts_dir, 'system.md')
        if os.path.exists(prompt_path):
            with open(prompt_path, 'r') as f:
                prompt = f.read()
        else:
            prompt = self._default_system_prompt()

        # Append personal prompt if it exists (gitignored, for personal context)
        personal_path = os.path.join(REPO_PATH, 'personal_prompt.md')
        if os.path.exists(personal_path):
            with open(personal_path, 'r') as f:
                personal = f.read().strip()
            if personal:
                prompt += "\n\n" + personal

        return prompt

    def _default_system_prompt(self) -> str:
        """Fallback system prompt if file not found."""
        return """You are a helpful assistant that prints responses on a thermal receipt printer.
Keep responses concise and well-formatted for a narrow paper width."""


# Global default config
default_config = Config()