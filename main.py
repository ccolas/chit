"""
Main entry point for Chit - the receipt printer spirit.

Modes:
- Default: Press Enter to record (keyboard-based)
- --hands-free: Wake word detection ("Hey Jarvis")
- --text: Type messages instead of voice
"""

import argparse
import signal
import sys
from typing import Optional

try:
    from .config import Config
    from .llm import LLMClient
    from .printer import ReceiptPrinter, validate_dsl
    from .voice import VoiceInput, HandsFreeVoiceInput
    from .llm.memory import process_chit_response, strip_memory_commands, extract_print_block
except ImportError:
    from config import Config
    from llm import LLMClient
    from printer import ReceiptPrinter, validate_dsl
    from voice import VoiceInput, HandsFreeVoiceInput
    from llm.memory import process_chit_response, strip_memory_commands, extract_print_block


class VoiceAssistant:
    """Voice assistant - press Enter to record."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.voice = VoiceInput(self.config)
        self.llm = LLMClient(self.config)
        self.printer = ReceiptPrinter(self.config)
        self._running = False

    def run(self):
        self._running = True
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        print("\n" + "=" * 50)
        print("  CHIT - VOICE MODE")
        print("=" * 50)
        print(f"LLM: {self.config.llm_model}")
        print(f"Whisper: {self.config.whisper_provider} ({self.config.whisper_model})")
        print()
        print("Controls:")
        print("  Press Enter to start recording, Enter again to stop")
        print("  Type 'reset' to clear conversation")
        print("  Type 'quit' to exit")
        print()

        self.voice.preload_model()

        while self._running:
            try:
                print("[Ready - press Enter to speak]")
                cmd = input().strip().lower()

                if cmd == 'quit' or cmd == 'q':
                    break
                elif cmd == 'reset' or cmd == 'r':
                    self.llm.reset_conversation("user_request")
                    print("[Conversation reset]")
                else:
                    print("[Recording... press Enter to stop]")
                    self.voice.start_recording()
                    input()
                    print("[Processing...]")
                    self._handle_recording()

            except EOFError:
                break
            except KeyboardInterrupt:
                break

        self._cleanup()

    def _handle_recording(self):
        try:
            text = self.voice.stop_and_transcribe()
            if text.strip():
                self._process_message(text)
            else:
                print("[No speech detected]")
        except Exception as e:
            print(f"[Voice error: {e}]")

    def _process_message(self, user_message: str):
        print(f"\n{'#' * 40}")
        print(f"### YOU")
        print(f"{'#' * 40}")
        print(f"{user_message}\n")

        try:
            def validate_response(response: str) -> str:
                print_block = extract_print_block(response)
                cleaned = strip_memory_commands(print_block)
                return validate_dsl(cleaned)

            print(f"{'#' * 40}")
            print(f"### CHIT")
            print(f"{'#' * 40}")
            response = self.llm.chat_with_validation(
                user_message,
                validator=validate_response,
                stream=True
            )

            try:
                from llm.memory import process_chit_response
                from datetime import datetime
                process_chit_response(response)
                print_block = extract_print_block(response)

                now = datetime.now()
                day = now.day
                suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
                timestamp = now.strftime(f"%A, {day}{suffix} %b, %H:%M")
                separator = f'line(pattern="%  ")\ntext("{timestamp}", size=12, font="silkscreen", align="center")\ngap(8)\n'

                self.printer.print_dsl(separator + print_block)
                print("[Printed]")
            except Exception as e:
                print(f"[Print error: {e}]")

        except Exception as e:
            print(f"[LLM error: {e}]")

    def _handle_shutdown(self, signum, frame):
        print("\n[Shutting down...]")
        self._running = False
        self._cleanup()
        sys.exit(0)

    def _cleanup(self):
        print("[Cleaning up...]")
        self.voice.cleanup()
        self.printer.disconnect()
        print("[Goodbye!]")


class HandsFreeAssistant:
    """Hands-free assistant with wake word detection."""

    LED_PIN = 22  # Optional LED indicator

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.llm = LLMClient(self.config)
        self.printer = ReceiptPrinter(self.config)
        self._running = False
        self._gpio = None
        self._led_pin = None

        # Try to set up LED on Raspberry Pi (optional)
        self._setup_led()

        self.voice = HandsFreeVoiceInput(
            self.config,
            led_callback=self._set_led if self._gpio else None,
            on_recording_start=self.printer.double_chirp,
            on_recording_stop=self.printer.long_chirp
        )

    def _setup_led(self):
        """Set up LED indicator on Raspberry Pi (optional)."""
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            self._led_pin = self.LED_PIN
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._led_pin, GPIO.OUT)
            GPIO.output(self._led_pin, GPIO.LOW)
            print(f"[LED initialized on GPIO {self._led_pin}]")
        except ImportError:
            pass  # Not on Pi, LED disabled

    def _set_led(self, on: bool):
        if self._gpio and self._led_pin:
            self._gpio.output(self._led_pin, self._gpio.HIGH if on else self._gpio.LOW)

    def run(self):
        self._running = True
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        print("\n" + "=" * 50)
        print("  CHIT - HANDS FREE MODE")
        print("=" * 50)
        print(f"LLM: {self.config.llm_model}")
        print(f"Whisper: {self.config.whisper_provider} ({self.config.whisper_model})")
        print()
        print("Say 'Jarvis' to activate (or press Enter)")
        print("Recording stops automatically when you pause speaking")
        print()

        self.voice.preload_models()
        self.voice.start()

        while self._running:
            try:
                text = self.voice.listen_and_transcribe()
                if text and text.strip():
                    self._process_message(text)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"[Error: {e}]")

        self._cleanup()

    def _process_message(self, user_message: str):
        print(f"\n{'#' * 40}")
        print(f"### YOU")
        print(f"{'#' * 40}")
        print(f"{user_message}\n")

        try:
            def validate_response(response: str) -> str:
                print_block = extract_print_block(response)
                cleaned = strip_memory_commands(print_block)
                return validate_dsl(cleaned)

            print(f"{'#' * 40}")
            print(f"### CHIT")
            print(f"{'#' * 40}")
            response = self.llm.chat_with_validation(
                user_message,
                validator=validate_response,
                stream=True
            )

            try:
                from llm.memory import process_chit_response
                from datetime import datetime
                process_chit_response(response)
                print_block = extract_print_block(response)

                now = datetime.now()
                day = now.day
                suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
                timestamp = now.strftime(f"%A, {day}{suffix} %b, %H:%M")
                separator = f'line(pattern="%  ")\ntext("{timestamp}", size=12, font="silkscreen", align="center")\ngap(8)\n'

                self.printer.print_dsl(separator + print_block)
                print("[Printed]")
            except Exception as e:
                print(f"[Print error: {e}]")

        except Exception as e:
            print(f"[LLM error: {e}]")

    def _handle_shutdown(self, signum, frame):
        print("\n[Shutting down...]")
        self._running = False
        self.voice.stop()
        self._cleanup()
        sys.exit(0)

    def _cleanup(self):
        print("[Cleaning up...]")
        self.voice.cleanup()
        self.printer.disconnect()
        if self._gpio:
            self._gpio.cleanup()
        print("[Goodbye!]")


class TextAssistant:
    """Text-based assistant - type messages instead of voice."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.llm = LLMClient(self.config)
        self.printer = ReceiptPrinter(self.config)
        self._running = False

    def run(self):
        self._running = True
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        print("\n" + "=" * 50)
        print("  CHIT - TEXT MODE")
        print("=" * 50)
        print(f"LLM: {self.config.llm_model}")
        print()
        print("Type your message and press Enter.")
        print("Type 'quit' to exit, 'reset' to clear conversation.")
        print()

        while self._running:
            try:
                user_input = input("> ").strip()

                if not user_input:
                    continue
                elif user_input.lower() in ('quit', 'q', 'exit'):
                    break
                elif user_input.lower() == 'reset':
                    self.llm.reset_conversation("user_request")
                    print("[Conversation reset]")
                else:
                    self._process_message(user_input)

            except EOFError:
                break
            except KeyboardInterrupt:
                break

        self._cleanup()

    def _process_message(self, user_message: str):
        print(f"\n{'#' * 40}")
        print(f"### YOU")
        print(f"{'#' * 40}")
        print(f"{user_message}\n")

        try:
            def validate_response(response: str) -> str:
                print_block = extract_print_block(response)
                cleaned = strip_memory_commands(print_block)
                return validate_dsl(cleaned)

            print(f"{'#' * 40}")
            print(f"### CHIT")
            print(f"{'#' * 40}")
            response = self.llm.chat_with_validation(
                user_message,
                validator=validate_response,
                stream=True
            )

            try:
                from llm.memory import process_chit_response
                from datetime import datetime
                process_chit_response(response)
                print_block = extract_print_block(response)

                now = datetime.now()
                day = now.day
                suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
                timestamp = now.strftime(f"%A, {day}{suffix} %b, %H:%M")
                separator = f'line(pattern="%  ")\ntext("{timestamp}", size=12, font="silkscreen", align="center")\ngap(8)\n'

                self.printer.print_dsl(separator + print_block)
                print("[Printed]")
            except Exception as e:
                print(f"[Print error: {e}]")

        except Exception as e:
            print(f"[LLM error: {e}]")

    def _handle_shutdown(self, signum, frame):
        print("\n[Shutting down...]")
        self._running = False
        self._cleanup()
        sys.exit(0)

    def _cleanup(self):
        self.printer.disconnect()
        print("[Goodbye!]")


def main():
    parser = argparse.ArgumentParser(description='Chit - A spirit in a thermal printer')
    parser.add_argument(
        '--model',
        default='google/gemini-2.0-flash-001',
        help='LLM model (default: google/gemini-2.0-flash-001)'
    )
    parser.add_argument(
        '--whisper',
        choices=['local', 'openai'],
        default='local',
        help='Whisper provider (default: local)'
    )
    parser.add_argument(
        '--whisper-model',
        default=None,
        help='Local Whisper model size: base, small, medium, large (default: medium)'
    )
    parser.add_argument(
        '--no-print',
        action='store_true',
        help='Disable printing (terminal only)'
    )
    parser.add_argument(
        '--hands-free',
        action='store_true',
        help='Enable hands-free mode with wake word detection'
    )
    parser.add_argument(
        '--text',
        action='store_true',
        help='Type messages instead of voice input'
    )

    args = parser.parse_args()

    config_kwargs = {
        'llm_model': args.model,
        'whisper_provider': args.whisper,
    }
    if args.whisper_model:
        config_kwargs['whisper_model'] = args.whisper_model
    config = Config(**config_kwargs)

    if args.text:
        assistant = TextAssistant(config)
    elif args.hands_free:
        assistant = HandsFreeAssistant(config)
    else:
        assistant = VoiceAssistant(config)

    if args.no_print:
        assistant.printer.print_response = lambda *args, **kwargs: None
        assistant.printer.print_text = lambda *args, **kwargs: None
        assistant.printer.print_dsl = lambda *args, **kwargs: None

    assistant.run()


if __name__ == '__main__':
    main()