#!/usr/bin/env python3
"""
Train a custom "Hey Chit" wake word model.

OpenWakeWord v0.6+ uses Google Colab for training - no local Python API.
This script provides instructions and helps prepare your samples.

Usage:
    1. First run: python record_wakeword.py  (to record samples)
    2. Then run: python train_wakeword.py    (for instructions)
"""

import os
import glob

SAMPLE_DIR = "wakeword_samples"
OUTPUT_DIR = "models"
MODEL_NAME = "hey_chit"


def main():
    print("=" * 50)
    print("  HEY CHIT - Wake Word Model Training")
    print("=" * 50)
    print()

    # Check for samples
    samples = glob.glob(os.path.join(SAMPLE_DIR, "*.wav"))

    if len(samples) == 0:
        print("No samples found yet.")
        print()
        print("Step 1: Record samples first:")
        print("  python record_wakeword.py")
        print()
        return

    print(f"Found {len(samples)} samples in '{SAMPLE_DIR}/'")
    print()

    # OpenWakeWord v0.6+ uses Colab for training
    print("=" * 50)
    print("  TRAINING OPTIONS")
    print("=" * 50)
    print()
    print("OpenWakeWord now uses Google Colab for training.")
    print()
    print("OPTION 1: Use Google Colab (Recommended)")
    print("-" * 40)
    print("1. Go to: https://colab.research.google.com/drive/1q1oe2zOyZp7UsB3jJiQ1IFn8z5YfjwEb")
    print()
    print("2. Upload your samples from:")
    print(f"   {os.path.abspath(SAMPLE_DIR)}/")
    print()
    print("3. Follow the notebook to train your model")
    print()
    print("4. Download the .onnx file and save it to:")
    print(f"   {os.path.abspath(OUTPUT_DIR)}/{MODEL_NAME}.onnx")
    print()
    print()
    print("OPTION 2: Use 'Hey Jarvis' (No training needed)")
    print("-" * 40)
    print("The built-in 'hey_jarvis' wake word works well.")
    print("Just say 'Hey Jarvis' instead of 'Hey Chit'.")
    print()
    print("Run: python main.py --hands-free")
    print()
    print()
    print("OPTION 3: Skip wake word, use text mode")
    print("-" * 40)
    print("Type messages instead of using voice:")
    print()
    print("Run: python main.py --text")
    print()

    # Create output directory for when they download the model
    os.makedirs(OUTPUT_DIR, exist_ok=True)


if __name__ == "__main__":
    main()
