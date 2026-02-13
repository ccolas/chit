"""
Chit DSL - A drawing language for thermal printer expression.

Chit writes code in this language to control how it appears on paper.
The DSL is parsed and executed against a PIL canvas.

Example:
    text("Hello world", size=24, font="iosevka")
    gap(20)
    center("WOW", size=48, font="press-start-2p")
    line(pattern="~")
    raw('''
       *
      ***
     *****
    ''')
"""

import re
import ast
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path


# Available fonts and their files
FONT_MAP = {
    # Monospace - clean, precise
    "iosevka": {
        "regular": "Iosevka-Regular.ttf",
        "bold": "Iosevka-Bold.ttf",
        "italic": "Iosevka-Regular.ttf",  # No italic, fallback
        "bold_italic": "Iosevka-Bold.ttf",
    },
    # Monospace - quirky, distinctive
    "space-mono": {
        "regular": "SpaceMono-Regular.ttf",
        "bold": "SpaceMono-Bold.ttf",
        "italic": "SpaceMono-Italic.ttf",
        "bold_italic": "SpaceMono-Bold.ttf",
    },
    # Typewriter - nostalgic, mechanical
    "courier": {
        "regular": "CourierPrime-Regular.ttf",
        "bold": "CourierPrime-Bold.ttf",
        "italic": "CourierPrime-Italic.ttf",
        "bold_italic": "CourierPrime-Bold.ttf",
    },
    # Pixel - retro gaming, 8-bit
    "pixel": {
        "regular": "PressStart2P-Regular.ttf",
        "bold": "PressStart2P-Regular.ttf",
        "italic": "PressStart2P-Regular.ttf",
        "bold_italic": "PressStart2P-Regular.ttf",
    },
    # Pixel - terminal, vintage computer
    "terminal": {
        "regular": "VT323-Regular.ttf",
        "bold": "VT323-Regular.ttf",
        "italic": "VT323-Regular.ttf",
        "bold_italic": "VT323-Regular.ttf",
    },
    # Pixel - tiny, compact
    "silkscreen": {
        "regular": "Silkscreen-Regular.ttf",
        "bold": "Silkscreen-Bold.ttf",
        "italic": "Silkscreen-Regular.ttf",
        "bold_italic": "Silkscreen-Bold.ttf",
    },
}

# Shorthand aliases
FONT_ALIASES = {
    "mono": "iosevka",
    "retro": "pixel",
    "8bit": "pixel",
    "vt": "terminal",
    "console": "terminal",
    "silk": "silkscreen",
    "tiny": "silkscreen",
}


@dataclass
class DrawState:
    """Current drawing state - cursor position, margins, etc."""
    x: int = 10  # Current x position (left margin)
    y: int = 10  # Current y position (cursor)
    left_margin: int = 10
    right_margin: int = 10
    line_spacing: float = 1.2  # Multiplier for line height


@dataclass
class Command:
    """A parsed DSL command."""
    name: str
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)


class ChitDSL:
    """Parser and executor for Chit's drawing language."""

    def __init__(self, width: int = 384, font_dir: str = None):
        self.width = width
        self.font_dir = font_dir or str(Path(__file__).parent / "fonts")
        self.font_cache: Dict[Tuple[str, int, bool, bool], ImageFont.FreeTypeFont] = {}
        self.default_font = "iosevka"
        self.default_size = 22

    def get_font(self, name: str, size: int, bold: bool = False, italic: bool = False) -> ImageFont.FreeTypeFont:
        """Load a font with caching."""
        # Resolve aliases
        name = FONT_ALIASES.get(name, name)
        if name not in FONT_MAP:
            name = self.default_font

        cache_key = (name, size, bold, italic)
        if cache_key in self.font_cache:
            return self.font_cache[cache_key]

        # Determine variant
        if bold and italic:
            variant = "bold_italic"
        elif bold:
            variant = "bold"
        elif italic:
            variant = "italic"
        else:
            variant = "regular"

        font_file = FONT_MAP[name][variant]
        font_path = f"{self.font_dir}/{font_file}"

        try:
            font = ImageFont.truetype(font_path, size)
        except Exception:
            font = ImageFont.load_default()

        self.font_cache[cache_key] = font
        return font

    def parse(self, code: str) -> List[Command]:
        """Parse DSL code into commands."""
        commands = []

        # Handle raw blocks specially - extract them first
        # Match raw("""...""") or raw("""...""", size=18) etc.
        raw_pattern = r'raw\s*\(\s*(?:"""|\'\'\')(.*?)(?:"""|\'\'\')\s*(?:,\s*([^)]*))?\)'
        raw_blocks = {}
        raw_counter = [0]

        def replace_raw(match):
            placeholder = f"__RAW_BLOCK_{raw_counter[0]}__"
            raw_blocks[placeholder] = match.group(1)
            raw_counter[0] += 1
            # Preserve additional kwargs if present
            extra_args = match.group(2)
            if extra_args:
                return f'raw("{placeholder}", {extra_args})'
            return f'raw("{placeholder}")'

        code = re.sub(raw_pattern, replace_raw, code, flags=re.DOTALL)

        # Parse line by line, handling multi-line function calls
        lines = code.strip().split('\n')
        current_statement = ""

        for line in lines:
            # Skip empty lines and comments
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue

            current_statement += " " + line if current_statement else line

            # Check if statement is complete (balanced parens)
            if current_statement.count('(') == current_statement.count(')'):
                cmd = self._parse_statement(current_statement.strip(), raw_blocks)
                if cmd:
                    commands.append(cmd)
                current_statement = ""

        return commands

    def _parse_statement(self, statement: str, raw_blocks: Dict[str, str]) -> Optional[Command]:
        """Parse a single statement into a Command."""
        # Match function call: name(args)
        match = re.match(r'(\w+)\s*\((.*)\)\s*$', statement, re.DOTALL)
        if not match:
            return None

        name = match.group(1)
        args_str = match.group(2).strip()

        # Parse arguments
        args = []
        kwargs = {}

        if args_str:
            try:
                # Use ast to safely parse the arguments
                # Wrap in a function call to parse
                fake_code = f"f({args_str})"
                tree = ast.parse(fake_code, mode='eval')
                call = tree.body

                for arg in call.args:
                    value = ast.literal_eval(arg)
                    # Check for raw block placeholder
                    if isinstance(value, str) and value in raw_blocks:
                        value = raw_blocks[value]
                    args.append(value)

                for keyword in call.keywords:
                    value = ast.literal_eval(keyword.value)
                    if isinstance(value, str) and value in raw_blocks:
                        value = raw_blocks[value]
                    kwargs[keyword.arg] = value

            except Exception as e:
                # If parsing fails, try simple string extraction for single arg
                if args_str.startswith('"') or args_str.startswith("'"):
                    try:
                        args = [ast.literal_eval(args_str)]
                    except:
                        pass

        return Command(name=name, args=args, kwargs=kwargs)

    def execute(self, commands: List[Command]) -> Image.Image:
        """Execute commands and return the resulting image."""
        # Create canvas (tall, will crop later)
        img = Image.new('RGB', (self.width, 3000), 'white')
        draw = ImageDraw.Draw(img)
        state = DrawState()

        for cmd in commands:
            self._execute_command(cmd, draw, state)

        # Crop to content
        img = img.crop((0, 0, self.width, state.y + 20))

        # Convert to 1-bit for thermal printing
        img = img.convert('1')

        return img

    def _execute_command(self, cmd: Command, draw: ImageDraw.ImageDraw, state: DrawState):
        """Execute a single command."""
        method = getattr(self, f'_cmd_{cmd.name}', None)
        if method:
            method(cmd.args, cmd.kwargs, draw, state)
        else:
            # Unknown command - try to treat as text
            self._cmd_text([cmd.name], {}, draw, state)

    def _cmd_text(self, args: List, kwargs: Dict, draw: ImageDraw.ImageDraw, state: DrawState):
        """Draw text at current position."""
        if not args:
            return

        content = str(args[0])
        size = kwargs.get('size', self.default_size)
        font_name = kwargs.get('font', self.default_font)
        bold = kwargs.get('bold', False)
        italic = kwargs.get('italic', False)
        align = kwargs.get('align', 'left')

        font = self.get_font(font_name, size, bold, italic)

        # Word wrap
        lines = self._wrap_text(content, font, self.width - state.left_margin - state.right_margin)

        for line in lines:
            bbox = font.getbbox(line)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            # Calculate x based on alignment
            if align == 'center':
                x = (self.width - text_width) // 2
            elif align == 'right':
                x = self.width - state.right_margin - text_width
            else:
                x = state.left_margin

            draw.text((x, state.y), line, font=font, fill='black')
            state.y += int(text_height * state.line_spacing)

    def _cmd_center(self, args: List, kwargs: Dict, draw: ImageDraw.ImageDraw, state: DrawState):
        """Shorthand for centered text."""
        kwargs['align'] = 'center'
        self._cmd_text(args, kwargs, draw, state)

    def _cmd_right(self, args: List, kwargs: Dict, draw: ImageDraw.ImageDraw, state: DrawState):
        """Shorthand for right-aligned text."""
        kwargs['align'] = 'right'
        self._cmd_text(args, kwargs, draw, state)

    def _cmd_gap(self, args: List, kwargs: Dict, draw: ImageDraw.ImageDraw, state: DrawState):
        """Add vertical space."""
        pixels = args[0] if args else kwargs.get('pixels', 20)
        state.y += int(pixels)

    def _cmd_line(self, args: List, kwargs: Dict, draw: ImageDraw.ImageDraw, state: DrawState):
        """Draw a horizontal separator line using a repeated pattern."""
        # Pattern defaults to "#", can be any string like "~", ". ", "#.#."
        pattern = kwargs.get('pattern', '#')
        size = kwargs.get('size', 16)

        font = self.get_font('iosevka', size)

        # Repeat pattern to fill width
        bbox = font.getbbox(pattern)
        pattern_width = bbox[2] - bbox[0]
        if pattern_width > 0:
            usable_width = self.width - state.left_margin - state.right_margin
            repeats = (usable_width // pattern_width) + 1
            line_text = (pattern * repeats)
        else:
            line_text = pattern * 40

        draw.text((state.left_margin, state.y), line_text, font=font, fill='black')
        state.y += int(size * state.line_spacing)

    def _cmd_indent(self, args: List, kwargs: Dict, draw: ImageDraw.ImageDraw, state: DrawState):
        """Set left margin / indent."""
        pixels = args[0] if args else kwargs.get('pixels', 20)
        state.left_margin = int(pixels)
        state.x = state.left_margin

    def _cmd_margin(self, args: List, kwargs: Dict, draw: ImageDraw.ImageDraw, state: DrawState):
        """Set margins."""
        if args:
            state.left_margin = int(args[0])
            state.right_margin = int(args[0])
        if 'left' in kwargs:
            state.left_margin = int(kwargs['left'])
        if 'right' in kwargs:
            state.right_margin = int(kwargs['right'])

    def _cmd_at(self, args: List, kwargs: Dict, draw: ImageDraw.ImageDraw, state: DrawState):
        """Move cursor to absolute position."""
        if len(args) >= 2:
            state.x = int(args[0])
            state.y = int(args[1])
        elif 'x' in kwargs:
            state.x = int(kwargs['x'])
        if 'y' in kwargs:
            state.y = int(kwargs['y'])

    def _cmd_raw(self, args: List, kwargs: Dict, draw: ImageDraw.ImageDraw, state: DrawState):
        """Draw raw text preserving exact spacing (for ASCII art)."""
        if not args:
            return

        content = str(args[0])
        size = kwargs.get('size', 18)
        font_name = kwargs.get('font', 'iosevka')

        font = self.get_font(font_name, size, bold=False, italic=False)

        # Draw each line exactly as-is
        lines = content.split('\n')

        # Remove leading/trailing empty lines
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()

        # Find minimum indentation to preserve relative spacing
        min_indent = float('inf')
        for line in lines:
            if line.strip():
                indent = len(line) - len(line.lstrip())
                min_indent = min(min_indent, indent)
        if min_indent == float('inf'):
            min_indent = 0

        char_bbox = font.getbbox('M')
        line_height = int((char_bbox[3] - char_bbox[1]) * 1.1)

        for line in lines:
            # Preserve spacing relative to minimum indent
            if line.strip():
                line = line[min_indent:] if len(line) > min_indent else line
            draw.text((state.left_margin, state.y), line, font=font, fill='black')
            state.y += line_height

    def _cmd_rect(self, args: List, kwargs: Dict, draw: ImageDraw.ImageDraw, state: DrawState):
        """Draw a rectangle."""
        width = kwargs.get('width', self.width - state.left_margin - state.right_margin)
        height = kwargs.get('height', 50)
        fill = kwargs.get('fill', False)
        char = kwargs.get('char', '#')

        x0 = state.left_margin
        y0 = state.y
        x1 = x0 + width
        y1 = y0 + height

        if fill:
            draw.rectangle([x0, y0, x1, y1], fill='black')
        else:
            draw.rectangle([x0, y0, x1, y1], outline='black', width=2)

        state.y = y1 + 10

    def _cmd_box(self, args: List, kwargs: Dict, draw: ImageDraw.ImageDraw, state: DrawState):
        """Draw text inside a box."""
        if not args:
            return

        content = str(args[0])
        padding = kwargs.get('padding', 10)
        char = kwargs.get('char', '#')
        size = kwargs.get('size', self.default_size)
        font_name = kwargs.get('font', self.default_font)

        font = self.get_font(font_name, size)

        # Calculate box dimensions
        lines = self._wrap_text(content, font, self.width - state.left_margin - state.right_margin - padding * 2)

        bbox = font.getbbox('Mg')  # Sample for height
        line_height = int((bbox[3] - bbox[1]) * state.line_spacing)
        text_height = line_height * len(lines)

        box_width = self.width - state.left_margin - state.right_margin
        box_height = text_height + padding * 2

        # Draw box outline
        draw.rectangle(
            [state.left_margin, state.y, state.left_margin + box_width, state.y + box_height],
            outline='black', width=2
        )

        # Draw text inside
        text_y = state.y + padding
        for line in lines:
            draw.text((state.left_margin + padding, text_y), line, font=font, fill='black')
            text_y += line_height

        state.y += box_height + 10

    def _cmd_spacing(self, args: List, kwargs: Dict, draw: ImageDraw.ImageDraw, state: DrawState):
        """Set line spacing multiplier."""
        if args:
            state.line_spacing = float(args[0])
        elif 'multiplier' in kwargs:
            state.line_spacing = float(kwargs['multiplier'])

    def _wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
        """Wrap text to fit within max_width pixels."""
        lines = []

        for paragraph in text.split('\n'):
            if not paragraph.strip():
                lines.append('')
                continue

            words = paragraph.split()
            current_line = ''

            for word in words:
                test_line = f"{current_line} {word}".strip()
                bbox = font.getbbox(test_line)

                if bbox[2] - bbox[0] <= max_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word

            if current_line:
                lines.append(current_line)

        return lines

    def render(self, code: str) -> Image.Image:
        """Parse and execute DSL code, returning the rendered image."""
        commands = self.parse(code)
        return self.execute(commands)


def render_chit_output(code: str, width: int = 384, font_dir: str = None) -> Image.Image:
    """Convenience function to render Chit DSL code to an image."""
    dsl = ChitDSL(width=width, font_dir=font_dir)
    return dsl.render(code)


def validate_dsl(code: str) -> Optional[str]:
    """
    Validate DSL code without rendering.

    Returns None if valid, or an error message string if invalid.
    Used for LLM retry logic.
    """
    try:
        dsl = ChitDSL()
        commands = dsl.parse(code)

        if not commands:
            return "No valid DSL commands found. Response should contain commands like text(), gap(), line(), etc."

        # Try to execute (but don't save the image)
        dsl.execute(commands)

        return None  # Valid

    except Exception as e:
        return f"DSL parse/render error: {str(e)}"


def test_all_commands() -> str:
    """
    Generate DSL code that tests all available commands.
    Returns the test code string.
    """
    return '''
# === FONT TESTS ===
text("FONT SHOWCASE", size=28, bold=True, align="center")
gap(10)
line(pattern="# ")
gap(15)

text("iosevka - clean monospace", size=20, font="iosevka")
text("space-mono - quirky mono", size=20, font="space-mono")
text("courier - typewriter feel", size=20, font="courier")
text("pixel - 8-bit retro", size=16, font="pixel")
text("terminal - old computer", size=22, font="terminal")
text("silkscreen - tiny pixel", size=16, font="silkscreen")

gap(20)
line()
gap(10)

# === SIZE TESTS ===
text("SIZE RANGE", size=28, bold=True, align="center")
gap(10)

text("size 12 - whisper", size=12)
text("size 16 - small", size=16)
text("size 22 - default", size=22)
text("size 26 - emphasis", size=26)
text("size 32 - loud", size=32)
text("size 48 - SHOUT", size=48)

gap(20)
line()
gap(10)

# === ALIGNMENT TESTS ===
text("ALIGNMENT", size=28, bold=True, align="center")
gap(10)

text("left aligned (default)")
text("centered text", align="center")
text("right aligned", align="right")

gap(20)
line()
gap(10)

# === BOLD TEST ===
text("STYLES", size=28, bold=True, align="center")
gap(10)

text("normal weight", size=22)
text("bold weight", size=22, bold=True)

gap(20)
line()
gap(10)

# === LINE PATTERNS ===
text("SEPARATORS", size=28, bold=True, align="center")
gap(10)

text("default #:", size=18)
line()
gap(5)

text("tilde ~:", size=18)
line(pattern="~")
gap(5)

text("spaced dots . :", size=18)
line(pattern=". ")
gap(5)

text("mixed #.#.:", size=18)
line(pattern="#.#.")
gap(5)

text("stars * :", size=18)
line(pattern="* ")

gap(20)
line()
gap(10)

# === GAP TESTS ===
text("VERTICAL GAPS", size=28, bold=True, align="center")
gap(10)

text("gap(5) below:")
gap(5)
text("small gap")

text("gap(30) below:")
gap(30)
text("big gap")

gap(20)
line()
gap(10)

# === INDENT TESTS ===
text("INDENTATION", size=28, bold=True, align="center")
gap(10)

text("no indent")
indent(30)
text("indent 30px")
indent(60)
text("indent 60px")
indent(10)
text("back to 10px")

gap(20)
line()
gap(10)

# === WORD WRAP TEST ===
text("WORD WRAPPING", size=28, bold=True, align="center")
gap(10)

text("This is a longer sentence that should automatically wrap to multiple lines because it exceeds the paper width.")
gap(10)
text("Short line.")

gap(20)
line()
gap(10)

# === RAW ASCII ART ===
text("ASCII ART", size=28, bold=True, align="center")
gap(10)

raw("""
      /\\
     /  \\
    /    \\
   /______\\
      ||
   ___||___
""", size=16)

gap(10)

raw("""
  .---.
 /     \\
|  o o  |
|   >   |
 \\ --- /
  '---'
""", size=14)

gap(20)
line()
gap(10)

# === COMBINED EXAMPLE ===
text("RECIPE CARD", size=32, font="pixel", align="center")
gap(5)
line(pattern="~.~.")
gap(10)

text("SCRAMBLED EGGS", size=26, bold=True)
gap(5)
text("a breakfast classic", size=16, font="courier")
gap(15)

text("1. Crack 3 eggs", size=18)
text("2. Add salt, whisk", size=18)
text("3. Butter in pan", size=18)
text("4. Low heat, stir", size=18)
text("5. Remove while wet", size=18)

gap(15)
line(pattern="~")
gap(10)

right("- Chit", size=20)
gap(5)
'''


def test_dsl_to_image(output_path: str = '/tmp/chit_dsl_test.png'):
    """Render DSL test to an image file."""
    code = test_all_commands()
    img = render_chit_output(code)
    img.save(output_path)
    print(f"Test image saved to {output_path} ({img.size[0]}x{img.size[1]})")
    return img


def test_dsl_to_printer():
    """Print DSL test directly to the thermal printer."""
    try:
        from printer import ReceiptPrinter
    except ImportError:
        from .printer import ReceiptPrinter

    code = test_all_commands()
    printer = ReceiptPrinter()
    printer.print_dsl(code)
    printer.disconnect()
    print("Test printed to thermal printer!")


# Test
if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--print':
        # Print to actual printer
        test_dsl_to_printer()
    else:
        # Just save to image
        test_dsl_to_image()
