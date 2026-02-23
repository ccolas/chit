"""
Chit Memory System - Markdown-based persistent memory.

Two files:
- memory/user.md: What Chit learns about the person talking to it
- memory/self.md: Chit's evolving sense of self

Primitives:
- remember("fact") - Append to user.md
- note_to_self("thought") - Append to self.md
- rewrite_memory("new content") - Replace user.md entirely
- rewrite_self("new content") - Replace self.md entirely
"""
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List


MEMORY_DIR = Path(__file__).parent.parent / "memory"
os.makedirs(MEMORY_DIR, exist_ok=True)
USER_FILE = MEMORY_DIR / "user.md"
SELF_FILE = MEMORY_DIR / "self.md"

# Suggest summarizing when files exceed this many lines
SUMMARIZE_THRESHOLD = 50


def _ensure_dir():
    """Ensure memory directory exists."""
    MEMORY_DIR.mkdir(exist_ok=True)


def _read_file(path: Path) -> str:
    """Read a memory file, return empty string if doesn't exist."""
    if path.exists():
        return path.read_text()
    return ""


def _write_file(path: Path, content: str):
    """Write content to a memory file."""
    _ensure_dir()
    path.write_text(content)


def _append_to_file(path: Path, line: str):
    """Append a line to a memory file."""
    _ensure_dir()
    content = _read_file(path)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    if content and not content.endswith("\n"):
        content += "\n"

    content += f"\n---\nDate: {timestamp}\n{line}\n"
    path.write_text(content)


def _count_lines(path: Path) -> int:
    """Count non-empty lines in a file."""
    content = _read_file(path)
    if not content:
        return 0
    return len([l for l in content.split("\n") if l.strip()])


# === Public API ===

def load_user_memory() -> str:
    """Load user memory content."""
    return _read_file(USER_FILE)


def load_self_memory() -> str:
    """Load self memory content."""
    return _read_file(SELF_FILE)


def get_memory_stats() -> dict:
    """Get stats about memory files."""
    return {
        "user_lines": _count_lines(USER_FILE),
        "self_lines": _count_lines(SELF_FILE),
        "user_needs_summary": _count_lines(USER_FILE) > SUMMARIZE_THRESHOLD,
        "self_needs_summary": _count_lines(SELF_FILE) > SUMMARIZE_THRESHOLD,
    }


def remember(fact: str):
    """Append a fact about the user."""
    _append_to_file(USER_FILE, fact)
    print(f"[remembered: {fact}]")


def note_to_self(thought: str):
    """Append a thought about self."""
    _append_to_file(SELF_FILE, thought)
    print(f"[noted: {thought}]")


def rewrite_memory(new_content: str):
    """Replace user memory entirely (for summarizing)."""
    _write_file(USER_FILE, new_content.strip() + "\n")
    print(f"[rewrote user memory]")


def rewrite_self(new_content: str):
    """Replace self memory entirely (for summarizing)."""
    _write_file(SELF_FILE, new_content.strip() + "\n")
    print(f"[rewrote self]")


def format_memories_for_prompt() -> str:
    """Format both memories for injection into system prompt."""
    user_mem = load_user_memory()
    self_mem = load_self_memory()
    stats = get_memory_stats()

    sections = []

    # Self memory
    if self_mem:
        sections.append("## Who I Am\n")
        sections.append(self_mem)
        if stats["self_needs_summary"]:
            sections.append(f"\n(This is getting long - {stats['self_lines']} lines. Consider using `rewrite_self()` to consolidate.)\n")

    # User memory
    if user_mem:
        sections.append("\n## What I Know About You\n")
        sections.append(user_mem)
        if stats["user_needs_summary"]:
            sections.append(f"\n(This is getting long - {stats['user_lines']} lines. Consider using `rewrite_memory()` to consolidate.)\n")

    if not sections:
        return ""

    return "\n".join(sections)


def extract_memory_commands(response: str) -> Tuple[str, List[dict]]:
    """
    Extract memory commands from response.
    Returns (cleaned_response, list_of_commands).

    Tags:
    - <remember>...</remember>
    - <self>...</self>
    - <rewrite-memory>...</rewrite-memory>
    - <rewrite-self>...</rewrite-self>
    """
    commands = []

    # Single-line memory tags
    patterns = [
        (r'<remember>(.*?)</remember>', 'remember'),
        (r'<self>(.*?)</self>', 'note_to_self'),
    ]

    # Multi-line rewrite tags
    rewrite_patterns = [
        (r'<rewrite-memory>(.*?)</rewrite-memory>', 'rewrite_memory'),
        (r'<rewrite-self>(.*?)</rewrite-self>', 'rewrite_self'),
    ]

    cleaned = response

    # Extract single-line tags
    for pattern, cmd_type in patterns:
        for match in re.finditer(pattern, cleaned, re.DOTALL):
            content = match.group(1).strip()
            if content:
                commands.append({'type': cmd_type, 'content': content})
        cleaned = re.sub(pattern, '', cleaned, flags=re.DOTALL)

    # Extract multi-line rewrite tags
    for pattern, cmd_type in rewrite_patterns:
        for match in re.finditer(pattern, cleaned, re.DOTALL):
            content = match.group(1).strip()
            if content:
                commands.append({'type': cmd_type, 'content': content})
        cleaned = re.sub(pattern, '', cleaned, flags=re.DOTALL)

    return cleaned, commands


def strip_memory_commands(dsl_code: str) -> str:
    """
    Remove memory commands from DSL code without executing them.
    Used for validation.
    """
    cleaned, _ = extract_memory_commands(dsl_code)
    return cleaned


def extract_print_block(response: str) -> str:
    """
    Extract all <print> blocks from a response, joined with sleep() between them.
    If no <print> block, returns the whole response (for backwards compatibility).
    The <thinking> block is discarded.
    """
    # Find all <print>...</print> blocks and the text between them
    block_pattern = re.compile(r'<print>\s*(.*?)\s*</print>', re.DOTALL)
    print_matches = list(block_pattern.finditer(response))
    if print_matches:
        if len(print_matches) == 1:
            return print_matches[0].group(1)
        # Multiple print blocks - look for sleep() between them
        parts = []
        for i, match in enumerate(print_matches):
            parts.append(match.group(1))
            if i < len(print_matches) - 1:
                # Get text between this </print> and next <print>
                between_text = response[match.end():print_matches[i + 1].start()]
                sleep_match = re.search(r'sleep\s*\(\s*(\d+\.?\d*)\s*\)', between_text)
                if sleep_match:
                    parts.append(f'sleep({sleep_match.group(1)})')
                else:
                    parts.append('sleep(2)')
        return '\n'.join(parts)

    # No <print> block — check if there's DSL code directly
    # (backwards compatibility, or if LLM doesn't use the tags)
    return response


def extract_wake_in(response: str) -> Optional[float]:
    """
    Extract wake_in(N) from response text.
    Returns hours as float, clamped to 1/60 (1 min) to 12, or None if not found.
    """
    match = re.search(r'wake_in\(\s*([\d.]+)\s*\)', response)
    if match:
        hours = float(match.group(1))
        return max(1/60, min(12.0, hours))
    return None


def process_chit_response(dsl_code: str) -> str:
    """
    Process Chit's response, executing any memory commands.
    Returns the cleaned DSL code (without memory commands).
    """
    cleaned_code, commands = extract_memory_commands(dsl_code)

    for cmd in commands:
        if cmd['type'] == 'remember':
            remember(cmd['content'])
        elif cmd['type'] == 'note_to_self':
            note_to_self(cmd['content'])
        elif cmd['type'] == 'rewrite_memory':
            rewrite_memory(cmd['content'])
        elif cmd['type'] == 'rewrite_self':
            rewrite_self(cmd['content'])

    return cleaned_code


# === CLI ===

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Chit Memory")
        print("-----------")
        stats = get_memory_stats()
        print(f"User memory: {stats['user_lines']} lines")
        print(f"Self memory: {stats['self_lines']} lines")
        print()

        self_mem = load_self_memory()
        if self_mem:
            print("=== WHO I AM ===")
            print(self_mem)

        user_mem = load_user_memory()
        if user_mem:
            print("=== WHAT I KNOW ABOUT YOU ===")
            print(user_mem)

        if not self_mem and not user_mem:
            print("No memories yet.")

        print()
        print("Commands:")
        print("  python memory.py show")
        print("  python memory.py clear")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "show":
        print(format_memories_for_prompt() or "No memories.")

    elif cmd == "clear":
        if USER_FILE.exists():
            USER_FILE.unlink()
        if SELF_FILE.exists():
            SELF_FILE.unlink()
        print("All memories cleared.")

    else:
        print(f"Unknown command: {cmd}")
