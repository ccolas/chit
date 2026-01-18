#!/usr/bin/env python3
"""Test printer sounds."""

import time
import sys
import os

# Add parent dir to path so we can import from chit/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printer import ReceiptPrinter

def test_sounds():
    print("Connecting to printer...")
    p = ReceiptPrinter()
    p.connect()

    print("\n1. Single chirp (1 line feed)")
    input("   Press Enter to hear...")
    p.chirp(1)

    time.sleep(0.5)

    print("\n2. START listening (two short chirps ~4mm)")
    input("   Press Enter to hear...")
    p.chirp_start()

    time.sleep(0.5)

    print("\n3. STOP listening (two longer chirps ~8mm)")
    input("   Press Enter to hear...")
    p.chirp_stop()

    time.sleep(0.5)

    print("\n4. Triple chirp")
    input("   Press Enter to hear...")
    p.chirp(1)
    time.sleep(0.15)
    p.chirp(1)
    time.sleep(0.15)
    p.chirp(1)

    time.sleep(0.5)

    print("\n5. Beep (if printer has buzzer, otherwise falls back to chirp)")
    input("   Press Enter to hear...")
    p.beep()

    print("\nDone! Disconnecting...")
    p.disconnect()

if __name__ == "__main__":
    test_sounds()