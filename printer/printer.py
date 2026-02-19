"""
Thermal printer module for the Receipt library.
Prints formatted text to ESC/POS compatible thermal printers (Excelvan ZJ-589, 58mm).

Key learnings from debugging:
- Solid horizontal lines (====) cause thermal head overheating and fade
- Use # characters for separators (varied patterns heat evenly)
- Image-based printing with Iosevka font works best for custom formatting
- Convert images to 1-bit mode and use impl='bitImageColumn'

Now supports Chit DSL - a drawing language that gives full creative control
over fonts, sizes, alignment, and layout.
"""

import os
import re
from datetime import datetime
from typing import Optional, List

try:
    from escpos.printer import Usb, Dummy
    ESCPOS_AVAILABLE = True
except ImportError:
    ESCPOS_AVAILABLE = False

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    from ..config import Config, default_config
    from .dsl import ChitDSL, render_chit_output
    from ..llm.memory import process_chit_response
except ImportError:
    try:
        from config import Config, default_config
        from printer.dsl import ChitDSL, render_chit_output
        from llm.memory import process_chit_response
    except ImportError:
        from config import Config, default_config
        from dsl import ChitDSL, render_chit_output
        from llm.memory import process_chit_response

class ReceiptPrinter:
    """Handles printing formatted text to thermal printers."""

    def __init__(self, config: Optional[Config] = None, dummy: bool = False):
        """
        Initialize the printer.

        Args:
            config: Configuration object (uses default if not provided)
            dummy: If True, use dummy printer for testing
        """
        self.config = config or default_config
        self.dummy = dummy
        self.printer = None
        self._load_fonts()

    def _load_fonts(self):
        """Load Iosevka fonts for image-based printing."""
        if not PIL_AVAILABLE:
            self.fonts = None
            return

        font_dir = self.config.font_dir
        try:
            self.fonts = {
                'title': ImageFont.truetype(f"{font_dir}/Iosevka-Bold.ttf", self.config.font_title_size),
                'heading': ImageFont.truetype(f"{font_dir}/Iosevka-Bold.ttf", self.config.font_heading_size),
                'normal': ImageFont.truetype(f"{font_dir}/Iosevka-Regular.ttf", self.config.font_normal_size),
                'small': ImageFont.truetype(f"{font_dir}/Iosevka-Regular.ttf", self.config.font_small_size),
            }
        except Exception:
            # Fallback to default font
            default = ImageFont.load_default()
            self.fonts = {
                'title': default,
                'heading': default,
                'normal': default,
                'small': default,
            }

    def connect(self):
        """Connect to the printer."""
        if not ESCPOS_AVAILABLE:
            raise ImportError("python-escpos not installed. Run: pip install python-escpos")

        if self.dummy:
            self.printer = Dummy()
        else:
            self.printer = Usb(
                self.config.printer_vendor_id,
                self.config.printer_product_id,
                profile="TM-T88III"  # Generic 58mm profile to suppress width warning
            )
        return True

    def disconnect(self):
        """Disconnect from printer."""
        if self.printer and not self.dummy:
            self.printer.close()
        self.printer = None

    def beep(self, times: int = 1):
        """
        Try to make the printer beep (if it has a buzzer).

        Most cheap 58mm printers don't have a buzzer, but some do.
        Falls back to chirp() if beep isn't supported.
        """
        if not self.printer:
            self.connect()

        try:
            # ESC BEL - standard buzzer command
            for _ in range(times):
                self.printer._raw(b'\x1b\x07')  # ESC BEL
        except Exception:
            # Fallback to motor noise
            self.chirp(times)

    def chirp(self, times: int = 1):
        """
        Make a short motor sound by feeding minimal paper.

        Feeds 1 line forward - makes a click/chirp sound.
        Uses very little paper (~1mm per chirp).
        """
        if not self.printer:
            self.connect()

        for _ in range(times):
            # Feed 1 line (minimal paper usage, but audible motor sound)
            self.printer._raw(b'\x1b\x64\x01')  # ESC d 1 - feed 1 line

    def chirp_start(self):
        """One short chirp - 'listening started' signal."""
        if not self.printer:
            self.connect()
        self.printer._raw(b'\x1b\x64\x01')  # 1 line

    def chirp_stop(self):
        """One short chirp - 'listening stopped' signal."""
        if not self.printer:
            self.connect()
        self.printer._raw(b'\x1b\x64\x01')  # 1 line

    def double_chirp(self):
        """Alias for chirp_start."""
        self.chirp_start()

    def long_chirp(self):
        """Alias for chirp_stop."""
        self.chirp_stop()

    def print_text(self, text: str, title: Optional[str] = None):
        """
        Print formatted text using image-based rendering.

        This method converts text to an image using Iosevka font,
        which produces consistent, readable output on thermal printers.

        Args:
            text: The text content to print
            title: Optional title/header for the print
        """
        if not self.printer:
            self.connect()

        if not PIL_AVAILABLE:
            # Fallback to text-only mode
            self._print_text_only(text, title)
            return

        # Create image
        img = self._create_text_image(text, title)

        # Print image (borders are drawn inside the image)
        p = self.printer
        p.image(img, impl='bitImageColumn')
        p.text("\n\n")  # margin for cutting

    def _create_text_image(self, text: str, title: Optional[str] = None) -> Image.Image:
        """
        Create a printable image from text.

        Args:
            text: Text content
            title: Optional title

        Returns:
            PIL Image in 1-bit mode ready for printing
        """
        width = self.config.printer_width
        fonts = self.fonts

        # Start with a tall canvas (we'll crop later)
        img = Image.new('RGB', (width, 2000), 'white')
        draw = ImageDraw.Draw(img)

        y = 5

        # Top border
        draw.text((5, y), "#" * 40, font=fonts['small'], fill='black')
        y += 30

        # Timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        ts_bbox = draw.textbbox((0, 0), timestamp, font=fonts['small'])
        ts_width = ts_bbox[2] - ts_bbox[0]
        draw.text(((width - ts_width) // 2, y), timestamp, font=fonts['small'], fill='black')
        y += 30

        # Main text with word wrapping
        lines = self._wrap_text(text, fonts['normal'], width - 20)
        for line in lines:
            draw.text((10, y), line, font=fonts['normal'], fill='black')
            y += 28

        y += 15

        # Footer - "Love, Chit."
        draw.text(((width // 2) - 30, y), "Love,", font=fonts['small'], fill='black')
        y += 22
        draw.text(((width // 2) - 25, y), "Chit.", font=fonts['small'], fill='black')
        y += 30

        # Bottom border
        draw.text((5, y), "#" * 40, font=fonts['small'], fill='black')
        y += 22

        # Crop and convert to 1-bit
        img = img.crop((0, 0, width, y))
        img = img.convert('1')

        return img

    def _wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
        """
        Wrap text to fit within max_width pixels.

        Args:
            text: Text to wrap
            font: Font to measure with
            max_width: Maximum width in pixels

        Returns:
            List of wrapped lines
        """
        lines = []

        # Split into paragraphs first
        paragraphs = text.split('\n')

        for paragraph in paragraphs:
            if not paragraph.strip():
                lines.append('')
                continue

            words = paragraph.split()
            current_line = ''

            for word in words:
                test_line = f"{current_line} {word}".strip()
                # Measure text width
                bbox = font.getbbox(test_line)
                text_width = bbox[2] - bbox[0]

                if text_width <= max_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word

            if current_line:
                lines.append(current_line)

        return lines

    def _print_text_only(self, text: str, title: Optional[str] = None):
        """Fallback text-only printing (no PIL)."""
        p = self.printer

        p.set(font='b')
        p.text("#" * self.config.printer_char_width + "\n")

        if title:
            p.set(align='center', bold=True)
            p.text(title + "\n")
            p.set(bold=False)

        p.set(align='left')
        p.text(datetime.now().strftime("%Y-%m-%d %H:%M") + "\n\n")

        # Simple word wrap
        for line in self._simple_wrap(text, self.config.printer_char_width - 2):
            p.text(line + "\n")

        p.text("\n")
        p.text("#" * self.config.printer_char_width + "\n\n\n\n")

    def _simple_wrap(self, text: str, width: int) -> List[str]:
        """Simple character-based word wrap."""
        lines = []
        for paragraph in text.split('\n'):
            words = paragraph.split()
            current = ''
            for word in words:
                if len(current) + len(word) + 1 <= width:
                    current += (' ' if current else '') + word
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
            if not paragraph.strip():
                lines.append('')
        return lines

    def is_dsl(self, text: str) -> bool:
        """
        Check if text appears to be Chit DSL code.

        DSL code contains function calls like text(), center(), line(), etc.
        """
        # DSL commands that indicate this is code, not plain text
        dsl_patterns = [
            r'^\s*text\s*\(',
            r'^\s*center\s*\(',
            r'^\s*right\s*\(',
            r'^\s*line\s*\(',
            r'^\s*gap\s*\(',
            r'^\s*raw\s*\(',
            r'^\s*indent\s*\(',
        ]

        for pattern in dsl_patterns:
            if re.search(pattern, text, re.MULTILINE):
                return True
        return False

    def print_dsl(self, code: str):
        """
        Print DSL code - parses and renders to the printer.

        This gives Chit full creative control over the output:
        fonts, sizes, alignment, spacing, ASCII art, etc.

        Supports chirp() commands for audio feedback (executed before/after print).

        Args:
            code: Chit DSL code
        """
        if not self.printer:
            self.connect()

        import time

        # Split code on sleep() commands into segments
        sleep_pattern = re.compile(r'^\s*sleep\s*\(\s*(\d+\.?\d*)\s*\)\s*$', re.MULTILINE)
        segments = sleep_pattern.split(code)
        # segments alternates: [code, sleep_time, code, sleep_time, code, ...]

        for i, segment in enumerate(segments):
            if i % 2 == 1:
                # This is a sleep duration
                duration = min(float(segment), 7)  # Max 10 seconds
                time.sleep(duration)
                continue

            segment = segment.strip()
            if not segment:
                continue

            # Extract and execute chirp commands
            chirp_pattern = re.compile(r'^\s*chirp\s*\((\d*)\)\s*$', re.MULTILINE)

            def execute_chirp(match):
                count = int(match.group(1)) if match.group(1) else 1
                count = min(count, 5)  # Max 5 chirps
                for j in range(count):
                    self.chirp(1)
                    if j < count - 1:
                        time.sleep(0.12)
                return ''  # Remove from code

            segment = chirp_pattern.sub(execute_chirp, segment).strip()
            if not segment:
                continue

            if not PIL_AVAILABLE:
                self._print_text_only(segment, None)
                continue

            try:
                # Render DSL to image
                dsl = ChitDSL(width=self.config.printer_width, font_dir=self.config.font_dir)
                img = dsl.render(segment)

                # Print
                self.printer.image(img, impl='bitImageColumn')

            except Exception as e:
                print(f"[DSL parse error: {e}, falling back to plain text]")
                self._print_text_only(segment, None)

    def print_response(self, text: str):
        """
        Smart print - auto-detects DSL vs plain text.

        If the text looks like DSL code, render it with full formatting.
        Otherwise, use the legacy plain text renderer.

        Also processes any remember() commands in the output - these
        are stored as memories but not printed.

        Args:
            text: Either DSL code or plain text
        """
        # Process and store any remember() commands
        text = process_chit_response(text)

        if self.is_dsl(text):
            self.print_dsl(text)
        else:
            self.print_text(text)

    def print_separator(self):
        """Print a visual separator line."""
        if not self.printer:
            self.connect()
        self.printer.text("#" * self.config.printer_char_width + "\n")

    def feed(self, lines: int = 4):
        """Feed paper for cutting."""
        if not self.printer:
            self.connect()
        self.printer.text("\n" * lines)


def test_printer():
    """Quick printer test."""
    printer = ReceiptPrinter(dummy=False)
    printer.connect()
    printer.print_text(
        "This is a test message from the Receipt library.\n\n"
        "If you can read this, the printer is working correctly.",
        title="Printer Test"
    )
    printer.disconnect()
    print("Test complete!")


if __name__ == '__main__':
    test_printer()