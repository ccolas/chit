"""
Main entry point for the Receipt library.
Handles button input, voice recording, LLM queries, and printing.

Two modes:
- laptop: Uses keyboard input (hold 'r' to record, 'c' to reset, 'q' to quit)
- raspberry: Uses GPIO buttons (hold record button, press reset button)
"""

import argparse
import signal
import sys
import time
import threading
from typing import Optional

try:
    from .config import Config
    from .llm import LLMClient
    from .printer import ReceiptPrinter
    from .voice import VoiceInput
    from .dsl import validate_dsl
    from .memory import process_chit_response, strip_memory_commands, extract_print_block
except ImportError:
    from config import Config
    from llm import LLMClient
    from printer import ReceiptPrinter
    from voice import VoiceInput
    from dsl import validate_dsl
    from memory import process_chit_response, strip_memory_commands, extract_print_block


class ReceiptAssistant:
    """Main assistant class coordinating voice, LLM, and printer."""

    def __init__(self, config: Optional[Config] = None):
        """Initialize the assistant."""
        self.config = config or Config()
        self.voice = VoiceInput(self.config)
        self.llm = LLMClient(self.config)
        self.printer = ReceiptPrinter(self.config)
        self._running = False

        # GPIO for Raspberry Pi mode
        self._gpio = None
        if self.config.backend == 'raspberry':
            self._setup_gpio()

    def _setup_gpio(self):
        """Set up GPIO for Raspberry Pi."""
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO

            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.config.record_button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(self.config.reset_button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

            print(f"[GPIO initialized]")
            print(f"  Record button: GPIO {self.config.record_button_pin}")
            print(f"  Reset button: GPIO {self.config.reset_button_pin}")
        except ImportError:
            print("[Warning: RPi.GPIO not available, falling back to laptop mode]")
            self.config.backend = 'laptop'

    def run(self):
        """Run the main loop."""
        self._running = True

        # Set up signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        print("\n" + "=" * 50)
        print("  RECEIPT ASSISTANT")
        print("=" * 50)
        print(f"Mode: {self.config.backend}")
        print(f"LLM: {self.config.llm_model}")
        print(f"Whisper: {self.config.whisper_provider} ({self.config.whisper_model})")
        print()

        # Pre-load Whisper model
        self.voice.preload_model()

        if self.config.backend == 'laptop':
            self._run_laptop_mode()
        else:
            self._run_raspberry_mode()

    def _run_laptop_mode(self):
        """Run in laptop mode using keyboard input."""
        print("Controls:")
        print("  Press Enter to start recording, Enter again to stop")
        print("  Type 'reset' to clear conversation")
        print("  Type 'quit' to exit")
        print()

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
                    # Start recording
                    print("[Recording... press Enter to stop]")
                    self.voice.start_recording()
                    input()  # Wait for Enter to stop
                    print("[Processing...]")
                    self._handle_voice_input_laptop()

            except EOFError:
                break
            except KeyboardInterrupt:
                break

        self._cleanup()

    def _handle_voice_input_laptop(self):
        """Handle voice input for laptop mode (called after recording stops)."""
        try:
            text = self.voice.stop_and_transcribe()
            if text.strip():
                self._process_message(text)
            else:
                print("[No speech detected]")
            print("\n[Ready - hold F11 to speak]")
        except Exception as e:
            print(f"[Voice error: {e}]")
            print("\n[Ready - hold F11 to speak]")

    def _run_raspberry_mode(self):
        """Run in Raspberry Pi mode using GPIO buttons."""
        if not self._gpio:
            print("[Error: GPIO not available]")
            return

        GPIO = self._gpio
        print("Ready! Hold record button to speak, press reset to clear.")
        print()

        recording = False

        while self._running:
            try:
                # Check record button (active low)
                record_pressed = GPIO.input(self.config.record_button_pin) == GPIO.LOW
                reset_pressed = GPIO.input(self.config.reset_button_pin) == GPIO.LOW

                if reset_pressed:
                    self.llm.reset_conversation("button_press")
                    print("[Conversation reset]")
                    time.sleep(0.5)  # Debounce

                elif record_pressed and not recording:
                    # Start recording
                    recording = True
                    self.voice.start_recording()

                elif not record_pressed and recording:
                    # Stop recording and process
                    recording = False
                    self._handle_voice_input()

                time.sleep(0.05)  # Small delay to prevent busy-waiting

            except KeyboardInterrupt:
                break

        self._cleanup()

    def _handle_voice_input(self):
        """Handle voice recording and processing."""
        try:
            # If not already recording (laptop mode), start now
            if self.config.backend == 'laptop':
                print("[Press Enter when done speaking...]")
                self.voice.start_recording()
                input()  # Wait for Enter

            # Stop and transcribe
            text = self.voice.stop_and_transcribe()

            if text.strip():
                self._process_message(text)
            else:
                print("[No speech detected]")

        except Exception as e:
            print(f"[Voice error: {e}]")

    def _process_message(self, user_message: str):
        """Process a message through LLM and print response."""
        print(f"\nYou: {user_message}\n")

        try:
            # Validator: extract print block, strip memory commands, validate DSL
            def validate_response(response: str) -> str:
                print_block = extract_print_block(response)
                cleaned = strip_memory_commands(print_block)
                return validate_dsl(cleaned)

            # Get LLM response with validation and retry
            print("Chit: ", end='')
            response = self.llm.chat_with_validation(
                user_message,
                validator=validate_response,
                stream=True
            )

            # Process memory commands from full response (they can be anywhere)
            # Then extract print block for printing
            try:
                from memory import process_chit_response
                process_chit_response(response)  # Handle <remember>, <self>, etc.
                print_block = extract_print_block(response)
                self.printer.print_dsl(print_block)  # Print just the DSL
                print("[Printed]")
            except Exception as e:
                print(f"[Print error: {e}]")

        except Exception as e:
            print(f"[LLM error: {e}]")

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals."""
        print("\n[Shutting down...]")
        self._running = False

    def _cleanup(self):
        """Clean up resources."""
        print("[Cleaning up...]")
        self.voice.cleanup()
        self.printer.disconnect()

        if self._gpio:
            self._gpio.cleanup()

        print("[Goodbye!]")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Receipt Assistant - Voice to Print')
    parser.add_argument(
        '--backend',
        choices=['laptop', 'raspberry'],
        default='laptop',
        help='Backend mode (default: laptop)'
    )
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
        help='Local Whisper model size (default: small for laptop, base for raspberry)'
    )
    parser.add_argument(
        '--no-print',
        action='store_true',
        help='Disable printing (terminal only)'
    )

    args = parser.parse_args()

    # Create config
    config_kwargs = {
        'backend': args.backend,
        'llm_model': args.model,
        'whisper_provider': args.whisper,
    }
    if args.whisper_model:
        config_kwargs['whisper_model'] = args.whisper_model
    config = Config(**config_kwargs)

    # Run assistant
    assistant = ReceiptAssistant(config)

    if args.no_print:
        # Override print methods to no-op
        assistant.printer.print_response = lambda *args, **kwargs: None
        assistant.printer.print_text = lambda *args, **kwargs: None

    assistant.run()


if __name__ == '__main__':
    main()