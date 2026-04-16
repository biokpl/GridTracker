#!/usr/bin/env python3
"""Mouse koordinatlarini ekrana yazar. Ctrl+C ile dur."""
import pyautogui, time, sys

print("=" * 40)
print("MOUSE KOORDINAT BULUCU")
print("Mouse'u istenen yere gotürun.")
print("Ctrl+C ile durdurun.")
print("=" * 40)

try:
    while True:
        x, y = pyautogui.position()
        print(f"\rx={x:4d}  y={y:4d}   ", end='', flush=True)
        time.sleep(0.1)
except KeyboardInterrupt:
    x, y = pyautogui.position()
    print(f"\nSon koordinat: x={x}, y={y}")
