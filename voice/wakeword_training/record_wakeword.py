#!/usr/bin/env python3
"""
Record wake word samples for training a custom "Hey Chit" model.

Usage:
    python record_wakeword.py

This will record 15 samples of you saying "Hey Chit".
Press Enter to start each recording, speak, then press Enter to stop.
"""

import os
import wave
import threading
import time

import sounddevice as sd

SAMPLE_DIR = "wakeword_samples"
SAMPLE_RATE = 16000
NUM_SAMPLES = 15


def record_sample(index: int) -> str:
    """Record a single sample."""
    print(f"\n[Sample {index + 1}/{NUM_SAMPLES}]")
    print("Press Enter, say 'Hey Chit', then press Enter again...")
    input()

    # Start recording
    stream = sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='int16',
        blocksize=1024
    )
    stream.start()

    frames = []
    print("Recording... say 'Hey Chit' now!")

    # Record in a loop until Enter is pressed
    stop_flag = threading.Event()

    def wait_for_enter():
        input()
        stop_flag.set()

    t = threading.Thread(target=wait_for_enter, daemon=True)
    t.start()

    while not stop_flag.is_set():
        data, overflowed = stream.read(1024)
        frames.append(bytes(data))

    stream.stop()
    stream.close()

    # Save to file
    filename = os.path.join(SAMPLE_DIR, f"hey_chit_{index + 1:02d}.wav")
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b''.join(frames))

    duration = len(frames) * 1024 / SAMPLE_RATE
    print(f"✓ Saved: {filename} ({duration:.1f}s)")

    return filename


def main():
    print("=" * 50)
    print("  HEY CHIT - Wake Word Sample Recorder")
    print("=" * 50)
    print()
    print(f"This will record {NUM_SAMPLES} samples of you saying 'Hey Chit'.")
    print("Try to vary your tone, speed, and distance from the mic.")
    print()
    print("Tips:")
    print("  - Say it naturally, like you're calling someone")
    print("  - Some fast, some slow")
    print("  - Some loud, some quiet")
    print("  - Move closer/farther from mic")
    print()

    # Create sample directory
    os.makedirs(SAMPLE_DIR, exist_ok=True)

    input("Press Enter to begin...")

    samples = []
    for i in range(NUM_SAMPLES):
        filename = record_sample(i)
        samples.append(filename)

        if i < NUM_SAMPLES - 1:
            time.sleep(0.5)

    print()
    print("=" * 50)
    print(f"Done! Recorded {len(samples)} samples in '{SAMPLE_DIR}/'")
    print()
    print("Next steps:")
    print("  1. Review the samples (play them back)")
    print("  2. Delete any bad ones and re-record")
    print("  3. Train the model with:")
    print()
    print("     openwakeword --train \\")
    print("       --model_name hey_chit \\")
    print(f"       --positive_samples {SAMPLE_DIR}/ \\")
    print("       --output_dir models/")
    print()


if __name__ == "__main__":
    main()
