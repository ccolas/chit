#!/usr/bin/env python3
"""Export a Chit conversation to a readable text file."""

import json
import re
import sys
import os

CONVERSATIONS_DIR = os.path.join(os.path.dirname(__file__), "conversations")

# Tags to extract and display
TAGS = ("thinking", "remember", "self", "rewrite-memory", "rewrite-self", "print")


def indent(text: str, prefix: str = "  ") -> str:
    """Indent every line, collapse 3+ blank lines into one."""
    collapsed = re.sub(r'\n{3,}', '\n\n', text.strip())
    return "\n".join(prefix + line for line in collapsed.splitlines())


def extract_tag(content: str, tag: str) -> str:
    """Extract content of a tag, return stripped text or empty string."""
    match = re.search(rf'<{tag}>(.*?)</{tag}>', content, re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_user_text(content: str) -> str:
    """Strip leading timestamp bracket from user message."""
    return re.sub(r'^\[.*?\]\n?', '', content.strip()).strip()


def format_conversation(conv_path: str) -> str:
    with open(conv_path) as f:
        data = json.load(f)

    out = []
    name = os.path.splitext(os.path.basename(conv_path))[0]
    out.append(f"CONVERSATION: {name}")
    out.append(f"Last updated: {data.get('last_updated', '?')}")
    out.append("=" * 50)
    out.append("")

    for msg in data["messages"]:
        role = msg["role"]
        content = msg["content"]

        if role == "user":
            ts_match = re.match(r'^\[(.*?)\]', content)
            timestamp = ts_match.group(1) if ts_match else ""
            text = extract_user_text(content)

            out.append(f"YOU  [{timestamp}]" if timestamp else "YOU")
            out.append(text)
            out.append("")

        elif role == "assistant":
            out.append("CHIT")

            # Show each tag block with blank line between them
            found_any = False
            for tag in TAGS:
                body = extract_tag(content, tag)
                if body:
                    if found_any:
                        out.append("")
                    out.append(f"  <{tag}>")
                    out.append(indent(body, "    "))
                    out.append(f"  </{tag}>")
                    found_any = True

            # Wake timer (outside tags)
            wake = re.search(r'wake_in\(([\d.]+)\)', content)
            if wake:
                if found_any:
                    out.append("")
                hours = float(wake.group(1))
                if hours < 1:
                    out.append(f"  [wake timer: {round(hours * 60)} min]")
                else:
                    out.append(f"  [wake timer: {hours}h]")
                found_any = True

            if not found_any:
                out.append("  (no output)")

            out.append("")

        out.append("-" * 50)
        out.append("")

    return "\n".join(out)


def main():
    conv_name = sys.argv[1] if len(sys.argv) > 1 else "default"
    conv_path = os.path.join(CONVERSATIONS_DIR, f"{conv_name}.json")

    if not os.path.exists(conv_path):
        print(f"Conversation not found: {conv_path}")
        sys.exit(1)

    output = format_conversation(conv_path)

    out_path = os.path.join(CONVERSATIONS_DIR, f"{conv_name}.txt")
    with open(out_path, "w") as f:
        f.write(output)

    print(f"Exported to {out_path}")


if __name__ == "__main__":
    main()