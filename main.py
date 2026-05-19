"""
Main entry point for Chit - the receipt printer spirit.

Modes:
- Default: Press Enter to record (keyboard-based)
- --hands-free: Wake word detection ("Hey Jarvis")
- --text: Type messages instead of voice
"""

import argparse
import os
import random
import signal
import sys
import threading
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

try:
    from .config import Config
    from .llm import LLMClient
    from .llm.client import CreditsExhaustedError
    from .printer import ReceiptPrinter, validate_dsl
    from .voice import VoiceInput, HandsFreeVoiceInput
    from .llm.memory import process_chit_response, strip_memory_commands, extract_print_block, extract_wake_in
except ImportError:
    from config import Config
    from llm import LLMClient
    from llm.client import CreditsExhaustedError
    from printer import ReceiptPrinter, validate_dsl
    from voice import VoiceInput, HandsFreeVoiceInput
    from llm.memory import process_chit_response, strip_memory_commands, extract_print_block, extract_wake_in

WAKE_FILE = Path(__file__).parent / "memory" / "next_wake.txt"


def _save_wake_time(target: datetime):
    """Persist scheduled wake time to disk."""
    WAKE_FILE.parent.mkdir(exist_ok=True)
    WAKE_FILE.write_text(target.isoformat())


def _load_wake_time() -> Optional[datetime]:
    """Load persisted wake time. Returns None if missing or unparseable."""
    try:
        if WAKE_FILE.exists():
            text = WAKE_FILE.read_text().strip()
            return datetime.fromisoformat(text)
    except Exception:
        pass
    return None


def _clear_wake_time():
    """Remove persisted wake time."""
    try:
        WAKE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


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

        except CreditsExhaustedError:
            print("[Credits exhausted]")
            self.printer.print_dsl('text("Credits are out", size=22, align="center")')
            sys.exit(1)
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
    """Hands-free assistant with wake word detection and spontaneous waking."""

    LED_PIN = 22  # Optional LED indicator
    QUIET_START = 23  # 11pm
    QUIET_END = 10    # 10am
    MAX_SPONTANEOUS_PER_DAY = 2

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.llm = LLMClient(self.config)
        self.printer = ReceiptPrinter(self.config)
        self._running = False
        self._gpio = None
        self._led_pin = None

        # Spontaneous wake state
        self._wake_timer: Optional[threading.Timer] = None
        self._spontaneous_count = 0
        self._spontaneous_date = ""
        self._last_interaction_time = datetime.now()

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

    def _schedule_next_wake(self, hours: Optional[float] = None):
        """Schedule the next spontaneous wake."""
        # Cancel existing timer
        if self._wake_timer:
            self._wake_timer.cancel()
            self._wake_timer = None

        # Reset daily counter if new day
        today = date.today().isoformat()
        if self._spontaneous_date != today:
            self._spontaneous_count = 0
            self._spontaneous_date = today

        # Check daily budget
        if self._spontaneous_count >= self.MAX_SPONTANEOUS_PER_DAY:
            print(f"[Spontaneous budget exhausted ({self._spontaneous_count}/{self.MAX_SPONTANEOUS_PER_DAY} today)]")
            return

        # Pick delay
        if hours is None:
            hours = random.uniform(1/60, 6.0)
        hours = max(1/60, min(12.0, hours))

        # Calculate target time
        now = datetime.now()
        target = now + timedelta(hours=hours)

        # Quiet hours: if target lands in 23:00–09:00, push to 09:00
        target_hour = target.hour
        if target_hour >= self.QUIET_START or target_hour < self.QUIET_END:
            # Push to 9am
            if target_hour >= self.QUIET_START:
                # Same night → next morning
                next_morning = target.replace(hour=self.QUIET_END, minute=0, second=0, microsecond=0) + timedelta(days=1)
            else:
                # Early morning → same day 9am
                next_morning = target.replace(hour=self.QUIET_END, minute=0, second=0, microsecond=0)
            target = next_morning

        delay_seconds = (target - now).total_seconds()
        if delay_seconds <= 0:
            return

        self._wake_timer = threading.Timer(delay_seconds, self._fire_spontaneous)
        self._wake_timer.daemon = True
        self._wake_timer.start()

        _save_wake_time(target)
        wake_time_str = target.strftime("%H:%M")
        print(f"[Next spontaneous wake at {wake_time_str} (in {delay_seconds/3600:.1f}h)]")

    def _load_saved_wake(self):
        """Restore a persisted wake time from before reboot."""
        saved = _load_wake_time()
        if saved is None:
            return None

        now = datetime.now()
        if saved <= now:
            # Wake time already passed — wake soon
            print(f"[Saved wake was at {saved.strftime('%H:%M')}, already passed — waking shortly]")
            _clear_wake_time()
            return 1/60  # 1 minute
        else:
            # Still in the future — use it
            hours = (saved - now).total_seconds() / 3600
            print(f"[Restored saved wake at {saved.strftime('%H:%M')} (in {hours:.1f}h)]")
            _clear_wake_time()
            return hours

    def _fire_spontaneous(self):
        """Called when the spontaneous timer fires."""
        _clear_wake_time()

        # Re-check daily budget
        today = date.today().isoformat()
        if self._spontaneous_date != today:
            self._spontaneous_count = 0
            self._spontaneous_date = today

        if self._spontaneous_count >= self.MAX_SPONTANEOUS_PER_DAY:
            print(f"[Spontaneous wake skipped — budget exhausted]")
            return

        print(f"\n[Spontaneous wake triggered]")
        self.voice.trigger_spontaneous()

    def _process_spontaneous(self):
        """Handle a spontaneous wake — send nudge to LLM."""
        # Increment daily counter
        today = date.today().isoformat()
        if self._spontaneous_date != today:
            self._spontaneous_count = 0
            self._spontaneous_date = today
        self._spontaneous_count += 1

        now = datetime.now()
        hours_since = (now - self._last_interaction_time).total_seconds() / 3600
        day_name = now.strftime("%A")
        time_str = now.strftime("%H:%M")

        prompt = (
            f"[Spontaneous wake — {day_name}, {time_str}. "
            f"{hours_since:.1f}h since last interaction. "
            f"No one is talking to you. You can think, remember, print something, "
            f"or just go back to sleep. You don't have to print anything.]"
        )

        print(f"\n{'#' * 40}")
        print(f"### SPONTANEOUS WAKE")
        print(f"{'#' * 40}")
        print(f"{prompt}\n")

        try:
            print(f"{'#' * 40}")
            print(f"### CHIT")
            print(f"{'#' * 40}")
            response = self.llm.chat(prompt, stream=True)

            self._last_interaction_time = datetime.now()

            # Process memories
            process_chit_response(response)

            # Check for print block
            print_block = extract_print_block(response)
            # If extract_print_block returns the raw response (no <print> tags), check if there's actual DSL
            has_print_tag = '<print>' in response
            if has_print_tag and print_block.strip():
                try:
                    cleaned = strip_memory_commands(print_block)
                    now = datetime.now()
                    day = now.day
                    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
                    timestamp = now.strftime(f"%A, {day}{suffix} %b, %H:%M")
                    separator = f'line(pattern="%  ")\ntext("{timestamp}", size=12, font="silkscreen", align="center")\ngap(8)\n'

                    self.printer.print_dsl(separator + cleaned)
                    print("[Printed]")
                except Exception as e:
                    print(f"[Print error: {e}]")
            else:
                print("[No print output — Chit stayed quiet]")

            # Schedule next wake from response
            wake_hours = extract_wake_in(response)
            self._schedule_next_wake(wake_hours)

        except CreditsExhaustedError:
            print("[Credits exhausted]")
        except Exception as e:
            print(f"[LLM error: {e}]")
            # Still schedule next wake on error
            self._schedule_next_wake()

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
        print("Say the wake word to activate (or press Enter)")
        print("Recording stops automatically when you pause speaking")
        print()

        self.voice.preload_models()
        self.voice.start()

        # Restore saved wake or schedule new one
        self._last_interaction_time = datetime.now()
        saved_hours = self._load_saved_wake()
        self._schedule_next_wake(saved_hours)

        while self._running:
            try:
                text, wake_type = self.voice.listen_and_transcribe()

                if wake_type == "spontaneous":
                    self._process_spontaneous()
                elif text and text.strip():
                    # User spoke — cancel timer, process, reschedule
                    if self._wake_timer:
                        self._wake_timer.cancel()
                        self._wake_timer = None
                    self._last_interaction_time = datetime.now()
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

            # Schedule next wake from response
            wake_hours = extract_wake_in(response)
            self._schedule_next_wake(wake_hours)

        except CreditsExhaustedError:
            print("[Credits exhausted]")
            self.printer.print_dsl('text("Credits are out", size=22, align="center")')
            sys.exit(1)
        except Exception as e:
            print(f"[LLM error: {e}]")
            # Still schedule next wake on error
            self._schedule_next_wake()

    def _handle_shutdown(self, signum, frame):
        print("\n[Shutting down...]")
        self._running = False
        if self._wake_timer:
            self._wake_timer.cancel()
        self.voice.stop()
        self._cleanup()
        sys.exit(0)

    def _cleanup(self):
        print("[Cleaning up...]")
        if self._wake_timer:
            self._wake_timer.cancel()
        self.voice.cleanup()
        self.printer.disconnect()
        if self._gpio:
            self._gpio.cleanup()
        print("[Goodbye!]")


class TextAssistant:
    """Text-based assistant with spontaneous waking support."""

    QUIET_START = 23
    QUIET_END = 9
    MAX_SPONTANEOUS_PER_DAY = 3

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.llm = LLMClient(self.config)
        self.printer = ReceiptPrinter(self.config)
        self._running = False

        # Spontaneous wake state
        self._wake_timer: Optional[threading.Timer] = None
        self._spontaneous_count = 0
        self._spontaneous_date = ""
        self._last_interaction_time = datetime.now()
        self._spontaneous_event = threading.Event()

    def _schedule_next_wake(self, hours: Optional[float] = None):
        """Schedule the next spontaneous wake."""
        if self._wake_timer:
            self._wake_timer.cancel()
            self._wake_timer = None

        today = date.today().isoformat()
        if self._spontaneous_date != today:
            self._spontaneous_count = 0
            self._spontaneous_date = today

        if self._spontaneous_count >= self.MAX_SPONTANEOUS_PER_DAY:
            print(f"[Spontaneous budget exhausted ({self._spontaneous_count}/{self.MAX_SPONTANEOUS_PER_DAY} today)]")
            return

        if hours is None:
            hours = random.uniform(0.5, 6.0)
        hours = max(1/60, min(12.0, hours))

        now = datetime.now()
        target = now + timedelta(hours=hours)

        target_hour = target.hour
        if target_hour >= self.QUIET_START or target_hour < self.QUIET_END:
            if target_hour >= self.QUIET_START:
                next_morning = target.replace(hour=self.QUIET_END, minute=0, second=0, microsecond=0) + timedelta(days=1)
            else:
                next_morning = target.replace(hour=self.QUIET_END, minute=0, second=0, microsecond=0)
            target = next_morning

        delay_seconds = (target - now).total_seconds()
        if delay_seconds <= 0:
            return

        self._wake_timer = threading.Timer(delay_seconds, self._fire_spontaneous)
        self._wake_timer.daemon = True
        self._wake_timer.start()

        _save_wake_time(target)
        wake_time_str = target.strftime("%H:%M")
        print(f"[Next spontaneous wake at {wake_time_str} (in {delay_seconds/3600:.1f}h)]")

    def _load_saved_wake(self):
        """Restore a persisted wake time from before reboot."""
        saved = _load_wake_time()
        if saved is None:
            return None

        now = datetime.now()
        if saved <= now:
            print(f"[Saved wake was at {saved.strftime('%H:%M')}, already passed — waking shortly]")
            _clear_wake_time()
            return 1/60
        else:
            hours = (saved - now).total_seconds() / 3600
            print(f"[Restored saved wake at {saved.strftime('%H:%M')} (in {hours:.1f}h)]")
            _clear_wake_time()
            return hours

    def _fire_spontaneous(self):
        """Called when spontaneous timer fires."""
        _clear_wake_time()

        today = date.today().isoformat()
        if self._spontaneous_date != today:
            self._spontaneous_count = 0
            self._spontaneous_date = today

        if self._spontaneous_count >= self.MAX_SPONTANEOUS_PER_DAY:
            print(f"\n[Spontaneous wake skipped — budget exhausted]")
            return

        self._spontaneous_event.set()

    def _process_spontaneous(self):
        """Handle a spontaneous wake."""
        self._spontaneous_event.clear()

        today = date.today().isoformat()
        if self._spontaneous_date != today:
            self._spontaneous_count = 0
            self._spontaneous_date = today
        self._spontaneous_count += 1

        now = datetime.now()
        hours_since = (now - self._last_interaction_time).total_seconds() / 3600
        day_name = now.strftime("%A")
        time_str = now.strftime("%H:%M")

        prompt = (
            f"[Spontaneous wake — {day_name}, {time_str}. "
            f"{hours_since:.1f}h since last interaction. "
            f"No one is talking to you. You can think, remember, print something, "
            f"or just go back to sleep. You don't have to print anything.]"
        )

        print(f"\n{'#' * 40}")
        print(f"### SPONTANEOUS WAKE")
        print(f"{'#' * 40}")
        print(f"{prompt}\n")

        try:
            print(f"{'#' * 40}")
            print(f"### CHIT")
            print(f"{'#' * 40}")
            response = self.llm.chat(prompt, stream=True)

            self._last_interaction_time = datetime.now()
            process_chit_response(response)

            has_print_tag = '<print>' in response
            print_block = extract_print_block(response)
            if has_print_tag and print_block.strip():
                try:
                    cleaned = strip_memory_commands(print_block)
                    now = datetime.now()
                    day = now.day
                    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
                    timestamp = now.strftime(f"%A, {day}{suffix} %b, %H:%M")
                    separator = f'line(pattern="%  ")\ntext("{timestamp}", size=12, font="silkscreen", align="center")\ngap(8)\n'
                    self.printer.print_dsl(separator + cleaned)
                    print("[Printed]")
                except Exception as e:
                    print(f"[Print error: {e}]")
            else:
                print("[No print output — Chit stayed quiet]")

            wake_hours = extract_wake_in(response)
            self._schedule_next_wake(wake_hours)

        except CreditsExhaustedError:
            print("[Credits exhausted]")
        except Exception as e:
            print(f"[LLM error: {e}]")
            self._schedule_next_wake()

    def _read_input_nonblocking(self, timeout=0.5):
        """Read a line from stdin without blocking, checking spontaneous event."""
        import select
        while self._running:
            if self._spontaneous_event.is_set():
                return None  # Signal spontaneous wake
            ready, _, _ = select.select([sys.stdin], [], [], timeout)
            if ready:
                line = sys.stdin.readline()
                if not line:  # EOF
                    raise EOFError
                return line.rstrip('\n')
        return None

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

        self._last_interaction_time = datetime.now()
        saved_hours = self._load_saved_wake()
        self._schedule_next_wake(saved_hours)

        while self._running:
            try:
                print("> ", end="", flush=True)
                user_input = self._read_input_nonblocking()

                if user_input is None:
                    # Spontaneous wake fired
                    if self._spontaneous_event.is_set():
                        self._process_spontaneous()
                    continue

                user_input = user_input.strip()
                if not user_input:
                    continue
                elif user_input.lower() in ('quit', 'q', 'exit'):
                    break
                elif user_input.lower() == 'reset':
                    self.llm.reset_conversation("user_request")
                    print("[Conversation reset]")
                else:
                    # User spoke — cancel timer, process, reschedule
                    if self._wake_timer:
                        self._wake_timer.cancel()
                        self._wake_timer = None
                    self._last_interaction_time = datetime.now()
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

            wake_hours = extract_wake_in(response)
            self._schedule_next_wake(wake_hours)

        except CreditsExhaustedError:
            print("[Credits exhausted]")
            self.printer.print_dsl('text("Credits are out", size=22, align="center")')
            sys.exit(1)
        except Exception as e:
            print(f"[LLM error: {e}]")
            self._schedule_next_wake()

    def _handle_shutdown(self, signum, frame):
        print("\n[Shutting down...]")
        self._running = False
        if self._wake_timer:
            self._wake_timer.cancel()
        self._cleanup()
        sys.exit(0)

    def _cleanup(self):
        if self._wake_timer:
            self._wake_timer.cancel()
        self.printer.disconnect()
        print("[Goodbye!]")


def main():
    parser = argparse.ArgumentParser(description='Chit - A spirit in a thermal printer')
    parser.add_argument(
        '--model',
        default='anthropic/claude-haiku-4.5',
        help='LLM model (default: anthropic/claude-haiku-4.5)'
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
    parser.add_argument(
        '--conv',
        default='default',
        help='Conversation name to load/save (default: "default")'
    )

    args = parser.parse_args()

    config_kwargs = {
        'llm_model': args.model,
        'whisper_provider': args.whisper,
        'conv_name': args.conv,
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