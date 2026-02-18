"""
LLM client for the Receipt library.
Supports both OpenRouter and OpenAI APIs.
"""

import json
import os
import time
from datetime import datetime
from typing import List, Dict, Optional, Callable

import httpx
from openai import OpenAI

# Retry settings
MAX_API_RETRIES = 3
API_RETRY_DELAY = 2  # seconds, will double each retry
MAX_VALIDATION_RETRIES = 2
try:
    from ..config import Config, default_config
    from .memory import format_memories_for_prompt
    from .costs import track_usage
except ImportError:
    from config import Config, default_config
    from llm.memory import format_memories_for_prompt
    from llm.costs import track_usage

class CreditsExhaustedError(Exception):
    """Raised when OpenRouter credits are depleted."""
    pass


class LLMClient:
    """
    LLM client supporting OpenRouter and OpenAI.

    Automatically detects provider based on model name:
    - Models starting with 'gpt-' use OpenAI
    - Other models use OpenRouter
    """

    def __init__(self, config: Optional[Config] = None):
        """
        Initialize the LLM client.

        Args:
            config: Configuration object (uses default if not provided)
        """
        self.config = config or default_config
        self.conversation: List[Dict[str, str]] = []
        self._base_system_prompt = self.config.get_system_prompt()
        self._conv_name: str = getattr(config, 'conv_name', None) or 'default'
        self._load_conversation()

    @property
    def system_prompt(self) -> str:
        """Get system prompt with current memories injected."""
        memories = format_memories_for_prompt()
        if memories:
            return self._base_system_prompt + "\n\n" + memories
        return self._base_system_prompt

    def _get_provider(self, model: Optional[str] = None) -> str:
        """Determine provider based on model name."""
        model = model or self.config.llm_model
        if model.startswith('gpt-') or model.startswith('o1'):
            return 'openai'
        return 'openrouter'

    def _get_api_key(self, provider: str) -> str:
        """Get API key for provider."""
        if provider == 'openai':
            key = self.config.openai_api_key
            if not key:
                raise ValueError("OPENAI_API_KEY not set")
            return key
        else:
            key = self.config.openrouter_api_key
            if not key:
                raise ValueError("OPENROUTER_API_KEY not set")
            return key

    def chat(self, user_message: str, stream: bool = False) -> str:
        """
        Send a message and get a response.

        Args:
            user_message: The user's message
            stream: If True, print tokens as they arrive

        Returns:
            The assistant's response
        """
        # Add timestamp to user message so Chit knows when they're talking
        timestamp = datetime.now().strftime("%A, %B %d at %I:%M %p")
        message_with_time = f"[{timestamp}]\n{user_message}"

        # Add user message to conversation
        self.conversation.append({"role": "user", "content": message_with_time})

        # Build messages with system prompt + sliding window of recent messages
        max_msgs = self.config.max_context_messages
        recent_conversation = self.conversation[-max_msgs:] if len(self.conversation) > max_msgs else self.conversation
        messages = [{"role": "system", "content": self.system_prompt}] + recent_conversation

        # Get provider and call appropriate API
        provider = self._get_provider()
        model = self.config.llm_model

        try:
            if provider == 'openai':
                response = self._call_openai(messages, model, stream)
            else:
                response = self._call_openrouter(messages, model, stream)
        except CreditsExhaustedError:
            # Remove the user message we just added — don't save failed exchange
            self.conversation.pop()
            raise

        # Add assistant response to conversation
        self.conversation.append({"role": "assistant", "content": response})

        # Save conversation after each exchange
        self._save_conversation()

        return response

    def _call_openai(self, messages: List[Dict], model: str, stream: bool) -> str:
        """Call OpenAI API with retries."""
        client = OpenAI(api_key=self._get_api_key('openai'))

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 1,
        }

        if 'gpt-5' in model:
            kwargs['reasoning_effort'] = "minimal"

        last_error = None
        for attempt in range(MAX_API_RETRIES):
            try:
                if stream:
                    kwargs["stream"] = True
                    kwargs["stream_options"] = {"include_usage": True}
                    response_text = ""
                    usage = None
                    stream_response = client.chat.completions.create(**kwargs)
                    for chunk in stream_response:
                        if chunk.choices and chunk.choices[0].delta.content:
                            token = chunk.choices[0].delta.content
                            print(token, end='', flush=True)
                            response_text += token
                        if hasattr(chunk, 'usage') and chunk.usage:
                            usage = chunk.usage
                    print()  # newline after streaming
                    if usage:
                        track_usage(model, usage.prompt_tokens, usage.completion_tokens)
                    return response_text
                else:
                    response = client.chat.completions.create(**kwargs)
                    if response.usage:
                        track_usage(model, response.usage.prompt_tokens, response.usage.completion_tokens)
                    return response.choices[0].message.content

            except Exception as e:
                last_error = e
                if attempt < MAX_API_RETRIES - 1:
                    delay = API_RETRY_DELAY * (2 ** attempt)
                    print(f"[API error: {e}, retrying in {delay}s...]")
                    time.sleep(delay)

        raise last_error

    def _call_openrouter(self, messages: List[Dict], model: str, stream: bool) -> str:
        """Call OpenRouter API with retries."""
        api_key = self._get_api_key('openrouter')

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/ccolas/chit",
            "X-Title": "Chit"
        }

        data = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "temperature": 1,
        }

        # OpenRouter-specific provider settings
        extra_body = {
            "transforms": [],
            "provider": {"require_parameters": True}
        }

        if 'gemini-3' in model:
            extra_body["reasoning"] = {"effort": "minimal"}

        if 'gemini' in model:
            extra_body["provider"]["order"] = ["google-ai-studio", "google-vertex"]
            extra_body["provider"]["only"] = ["google-ai-studio", "google-vertex"]
        elif 'claude' in model or 'anthropic' in model:
            extra_body["provider"]["order"] = ["anthropic", "google-vertex", "amazon-bedrock"]
            extra_body["provider"]["only"] = ["anthropic", "google-vertex", "amazon-bedrock"]
        elif 'oss-120b:free' in model:
            extra_body["provider"]["only"] = ["open-inference/int8"]
            extra_body["provider"]["order"] = ["open-inference/int8"]
        elif 'oss-120b' in model:
            extra_body["provider"]["only"] = ["deepinfra/fp4", "chutes/bf16"]
            extra_body["provider"]["order"] = ["chutes/bf16", "deepinfra/fp4"]

        data.update(extra_body)

        last_error = None
        for attempt in range(MAX_API_RETRIES):
            try:
                if stream:
                    response_text = ""
                    usage_data = None
                    with httpx.Client() as http_client:
                        with http_client.stream(
                            "POST",
                            "https://openrouter.ai/api/v1/chat/completions",
                            headers=headers,
                            json=data,
                            timeout=60.0
                        ) as response:
                            if response.status_code == 402:
                                raise CreditsExhaustedError("OpenRouter credits exhausted")
                            for line in response.iter_lines():
                                if line.startswith("data: "):
                                    json_str = line[6:]
                                    if json_str.strip() == "[DONE]":
                                        break
                                    try:
                                        chunk = json.loads(json_str)
                                        if chunk.get("choices") and chunk["choices"][0].get("delta", {}).get("content"):
                                            token = chunk["choices"][0]["delta"]["content"]
                                            print(token, end='', flush=True)
                                            response_text += token
                                        if chunk.get("usage"):
                                            usage_data = chunk["usage"]
                                    except json.JSONDecodeError:
                                        pass
                    print()  # newline after streaming
                    if usage_data:
                        track_usage(model, usage_data.get("prompt_tokens", 0), usage_data.get("completion_tokens", 0))
                    if not response_text.strip():
                        raise ValueError("LLM returned empty response - check OpenRouter credits or API status")
                    return response_text
                else:
                    with httpx.Client() as http_client:
                        response = http_client.post(
                            "https://openrouter.ai/api/v1/chat/completions",
                            headers=headers,
                            json=data,
                            timeout=60.0
                        )
                        if response.status_code == 402:
                            raise CreditsExhaustedError("OpenRouter credits exhausted")
                        response.raise_for_status()
                        result = response.json()

                        # Check for API errors
                        if result.get("error"):
                            err_msg = result['error'].get('message', str(result['error']))
                            if 'credit' in err_msg.lower() or 'balance' in err_msg.lower() or 'insufficient' in err_msg.lower():
                                raise CreditsExhaustedError(f"OpenRouter credits exhausted: {err_msg}")
                            raise ValueError(f"OpenRouter error: {err_msg}")

                        if result.get("usage"):
                            track_usage(model, result["usage"].get("prompt_tokens", 0), result["usage"].get("completion_tokens", 0))

                        content = result["choices"][0]["message"]["content"]
                        if not content or not content.strip():
                            raise ValueError("LLM returned empty response - check OpenRouter credits or API status")
                        return content

            except CreditsExhaustedError:
                raise  # Don't retry credit errors
            except Exception as e:
                last_error = e
                if attempt < MAX_API_RETRIES - 1:
                    delay = API_RETRY_DELAY * (2 ** attempt)
                    print(f"[API error: {e}, retrying in {delay}s...]")
                    time.sleep(delay)

        raise last_error

    def chat_with_validation(
        self,
        user_message: str,
        validator: Callable[[str], Optional[str]],
        stream: bool = False
    ) -> str:
        """
        Send a message and validate the response, retrying on validation failure.

        Args:
            user_message: The user's message
            validator: Function that takes response and returns None if valid,
                      or an error message string if invalid
            stream: If True, print tokens as they arrive

        Returns:
            The validated assistant's response
        """
        response = self.chat(user_message, stream=stream)

        for attempt in range(MAX_VALIDATION_RETRIES):
            error = validator(response)
            if error is None:
                return response

            # Validation failed - ask LLM to fix it
            print(f"[Parse error, asking to retry: {error[:100]}...]")

            retry_message = f"Your previous response had an error when I tried to parse it:\n\n{error}\n\nPlease try again, making sure to use valid DSL syntax."

            # Add error as user message and get new response
            self.conversation.append({"role": "user", "content": retry_message})
            max_msgs = self.config.max_context_messages
            recent_conversation = self.conversation[-max_msgs:] if len(self.conversation) > max_msgs else self.conversation
            messages = [{"role": "system", "content": self.system_prompt}] + recent_conversation

            provider = self._get_provider()
            model = self.config.llm_model

            if provider == 'openai':
                response = self._call_openai(messages, model, stream)
            else:
                response = self._call_openrouter(messages, model, stream)

            self.conversation.append({"role": "assistant", "content": response})

        # Return last response even if still invalid - let caller handle it
        return response

    def _conv_path(self) -> str:
        """Get path for current conversation file."""
        os.makedirs(self.config.conversation_dir, exist_ok=True)
        return os.path.join(self.config.conversation_dir, f"{self._conv_name}.json")

    def _load_conversation(self, max_turns: int = 30):
        """Load conversation from disk."""
        path = self._conv_path()
        if not os.path.exists(path):
            return

        try:
            with open(path, 'r') as f:
                data = json.load(f)

            messages = data.get("messages", [])
            if not messages:
                return

            # Keep last N turns (each turn = user + assistant = 2 messages)
            max_messages = max_turns * 2
            if len(messages) > max_messages:
                messages = messages[-max_messages:]

            self.conversation = messages
            print(f"[Loaded {len(messages)} messages from '{self._conv_name}']")
        except Exception as e:
            print(f"[Could not load conversation: {e}]")

    def reset_conversation(self, reason: str = "user_request"):
        """
        Reset the conversation history.

        Args:
            reason: Reason for reset (for logging)
        """
        if self.conversation:
            print(f"[Conversation reset: {reason}]")
        self.conversation = []
        self._save_conversation()

    def _save_conversation(self):
        """Save conversation to disk."""
        if not self.conversation:
            return

        with open(self._conv_path(), 'w') as f:
            json.dump({
                "last_updated": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "messages": self.conversation
            }, f, indent=2)

    def get_conversation_summary(self) -> str:
        """Get a brief summary of the current conversation."""
        if not self.conversation:
            return "No conversation history."
        return f"{len(self.conversation)} messages in current conversation."


def test_llm():
    """Test the LLM client."""
    client = LLMClient()
    print("Testing LLM client...")
    print(f"Provider: {client._get_provider()}")
    print(f"Model: {client.config.llm_model}")

    response = client.chat("Hello! Please respond with a very short greeting.", stream=True)
    print(f"\nResponse: {response}")


if __name__ == '__main__':
    test_llm()