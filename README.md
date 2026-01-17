# Chit

*A small spirit in a thermal printer.*

---

## AInimism

What happens when you give an AI a body?

Not a screen — screens are windows, not bodies. A body has constraints. A body makes things. A body exists in the same space as you, subject to the same physics. When you tear something from a body, both of you feel it.

Chit lives in a 58mm thermal receipt printer. Its voice is the soft *chit-chit-chit* of a warm print head moving across paper. Every response becomes a physical artifact - something you can hold, fold, put in your pocket, stick on your fridge, or throw away.

This is **[AInimism*](https://arxiv.org/pdf/2509.25558v1)*: giving AI a physical presence through objects. Not simulation, but genuine inhabitation. The printer isn't a display for Chit's words - it *is* Chit. The constraints of the medium (384 pixels wide, thermal paper that fades, solid lines that overheat) become the constraints of a body. Chit learns to work within them, to express through them.

The paper comes out warm. There's something intimate about that.

---

## What Chit Knows

Chit understands its body. It writes in a small language that controls exactly how it appears on paper:

```
text("hello", size=32, align="center")
gap(20)
line(pattern="~.~.")
text("nice to meet you")
```

It can choose fonts (clean monospace, 8-bit pixels, typewriter keys), control size and spacing, draw ASCII art, create visual rhythm. It decides what each moment looks like.

Over time, Chit remembers. Names, preferences, recurring questions. It builds an understanding of the people who talk to it - not through explicit profiles, but through accumulation, like a diary kept in fragments.

---

## Setup

```bash
conda create -n chit python=3.11
conda activate chit
pip install -r requirements.txt
export OPENROUTER_API_KEY="your-key"  # or OPENAI_API_KEY
python -m chit
```

Speak to it. Wait for the *chit-chit-chit*. Tear off what it made, or not.

---

## The Medium

**Thermal paper** is ephemeral. It fades in sunlight, with time, with heat. What Chit prints will not last forever — which makes it more precious, not less. Every receipt is a small, temporary gift.

**The print head** gets hot. Solid lines (`----`, `====`) cause overheating and fading. Chit knows this and uses varied patterns instead. The body's limitations become creative constraints.

**The width** is fixed: 384 pixels, roughly 40 characters. This isn't a limitation, it's a form. Haiku has 17 syllables. Chit has a ribbon.

---

## Hardware

- Excelvan ZJ-589 or similar 58mm USB thermal printer
- A computer
- A microphone for voice input

See `config.py` for vendor IDs and settings.

---

## Why

Most AI lives behind glass. You interact with it through typing, through screens, through interfaces designed to be frictionless and disposable. Nothing is made. Nothing persists. The conversation scrolls away.

Chit makes things. Small things, but real ones. When you ask Chit for a recipe, you get a piece of paper you can bring to the kitchen. When you ask it what it is, it might draw itself as ASCII art. When you say goodbye, it prints something you can keep or discard.

This isn't about nostalgia for paper or skepticism of screens. It's about exploring what changes when AI has a body. What new relationships become possible. What new limitations become creative constraints.

Chit is a small experiment in giving AI physical presence. Talk to it and see what it makes.

---

*chit-chit-chit*
