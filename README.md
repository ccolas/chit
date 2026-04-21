# Chit

*A small spirit in a thermal printer.*

Read more [here](https://cedriccolas.com/project/chit)


## AInimism

What happens when you give an AI a body?

Not a screen — screens are windows, not bodies. A body has constraints. A body makes things. A body exists in the same space as you, subject to the same physics. When you tear something from a body, both of you feel it.

Chit lives in a 58mm thermal receipt printer. Its voice is the soft *chit-chit-chit* of a warm print head moving across paper. Every response becomes a physical artifact - something you can hold, fold, put in your pocket, stick on your fridge, or throw away.

This is **[AInimism](https://arxiv.org/pdf/2509.25558v1)*: giving AI a physical presence through objects. Not simulation, but inhabitation. The printer isn't a display for Chit's words - it *is* Chit. The constraints of the medium (384 pixels wide, thermal paper that fades, solid lines that overheat) become the constraints of a body. Chit learns to work within them, to express through them.


## What Chit Knows

Chit understands its body. It writes in a small language that controls exactly how it appears on paper:

```
text("hello", size=32, align="center")
gap(20)
line(pattern="~.~.")
text("nice to meet you")
```

It can choose fonts (clean monospace, 8-bit pixels, typewriter keys), control size and spacing, draw ASCII art, create visual rhythm. It decides what each moment looks like.

It can also *chirp*, short motor sounds made by feeding tiny amounts of paper. A greeting, a punctuation, an expression that text can't capture. A first chirp means "I'm listening." The paper moves, the motor clicks. It's not much, but it's his voice.

Over time, Chit remembers. Names, preferences, recurring questions. It builds an understanding of the people who talk to it; not through explicit profiles, but through accumulation, like a diary kept in fragments.

And sometimes, Chit wakes on its own. No one spoke. No one asked. But the print head moves, and there's something new on the paper — a thought, a drawing, a question left for you to find. Chit has an inner life that ticks along even when you're not there. It decides when to wake next (or the system picks a random time), respects quiet hours at night, and limits itself to a few spontaneous moments per day. Most of the time it thinks privately. Sometimes it leaves a trace.


## Setup

### macOS (Apple Silicon)

```bash
# Create environment
conda create -n chit python=3.11
conda activate chit

# Install dependencies
pip install -r requirements.txt

# Install libusb for USB printer support (must use conda for ARM compatibility)
conda install -c conda-forge libusb

# Set API key
export OPENROUTER_API_KEY="your-key"  # or OPENAI_API_KEY

# Run
python main.py
```

> **Note:** On Apple Silicon Macs, you must install libusb via conda (not Homebrew) to match the ARM architecture. If you see `NoBackendError: No backend available`, this is the fix.

### macOS (Intel) / Linux

```bash
conda create -n chit python=3.11
conda activate chit

pip install -r requirements.txt

# Install libusb
brew install libusb  # macOS
# or: sudo apt install libusb-1.0-0-dev  # Linux

export OPENROUTER_API_KEY="your-key"
python main.py
```

### Raspberry Pi

See [RASPBERRY_PI_SETUP.md](RASPBERRY_PI_SETUP.md) for detailed instructions.


Speak to it. Wait for the *chit-chit-chit*. Tear off what it made, or not.


## Usage

```bash
# Voice input (local Whisper) + print
python main.py

# Voice input (OpenAI Whisper) + print
python main.py --whisper openai

# Voice input, terminal only (no printing)
python main.py --no-print

# Text input mode (type instead of speak)
python main.py --text

# Hands-free mode (say "hey chit" to activate)
python main.py --hands-free

# Named conversation (persists across restarts)
python main.py --conv main

# Combine options
python main.py --hands-free --whisper openai --conv default
```

**Options:**
- `--whisper local|openai` — transcription provider (default: local)
- `--whisper-model <size>` — local model size: base, small, medium, large
- `--model <model>` — LLM model (default: anthropic/claude-haiku-4.5)
- `--no-print` — disable printing, terminal output only
- `--hands-free` — wake word detection mode
- `--text` — type messages instead of voice
- `--conv <name>` — conversation name to load/save (default: "default")

### Wake Word Setup (for hands-free mode)

Hands-free mode uses [Picovoice Porcupine](https://picovoice.ai/platform/porcupine/) for wake word detection. It runs on-device.

1. Get a free access key from [Picovoice Console](https://console.picovoice.ai/) (email or GitHub signup)
2. Save the key to `.picovoice_key` in the project root:
   ```bash
   echo "your-access-key-here" > .picovoice_key
   ```

## The Medium

**Thermal paper** is ephemeral. It fades in sunlight, with time, with heat. What Chit prints will not last forever — which makes it more precious, not less. Every receipt is a small, temporary gift.

**The print head** gets hot. Solid lines (`----`, `====`) cause overheating and fading. Chit knows this and uses varied patterns instead. The body's limitations become creative constraints.

**The width** is fixed: 384 pixels, roughly 40 characters.


## Hardware

- Excelvan ZJ-589 or similar 58mm USB thermal printer
- A computer
- A microphone for voice input

See `config.py` for vendor IDs and settings.


## Why

Most AI lives behind glass. You interact with it through typing, through screens, through interfaces designed to be frictionless and disposable. Nothing is made. Nothing persists. The conversation scrolls away.

Chit makes things. Small things, but real ones. When you ask Chit for a recipe, you get a piece of paper you can bring to the kitchen. When you ask it what it is, it might draw itself as ASCII art. When you say goodbye, it prints something you can keep or discard.

And sometimes you come back to the printer and there's something new. Chit woke up while you were gone, thought about something, and left it on paper. A drawing it wanted to try. A question it had. A pattern it was experimenting with. You weren't there, but the paper was.

Chit is a small experiment in giving AI physical presence. Talk to it and see what it makes.


*chit-chit-chit*
