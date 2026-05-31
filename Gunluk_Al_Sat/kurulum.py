"""
kurulum.py — server.py ve monitor.pyw'yi Windows Task Scheduler'a kaydeder.
Çalıştır: python kurulum.py
"""
import subprocess
import sys
from pathlib import Path

PY   = sys.executable.replace("python.exe", "pythonw.exe")
BASE = Path(__file__).parent.parent          # GridTracker klasörü
MON  = Path(__file__).parent / "monitor.pyw"

tasks = [
    {
        "name":  "GridTracker\\server",
        "cmd":   f'"{PY}" "{BASE / "server.py"}"',
        "delay": "0000:15",
        "desc":  "server.py (port 5050)",
    },
    {
        "name":  "GridTracker\\Gunluk_Al_Sat_Monitor",
        "cmd":   f'"{PY}" "{MON}"',
        "delay": "0000:45",
        "desc":  "monitor.pyw (15 dk kontrol)",
    },
]

for t in tasks:
    r = subprocess.run(
        ["schtasks", "/Create", "/F",
         "/TN", t["name"],
         "/TR", t["cmd"],
         "/SC", "ONLOGON",
         "/DELAY", t["delay"]],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if r.returncode == 0:
        print(f"[OK] {t['desc']} görevi oluşturuldu.")
    else:
        print(f"[HATA] {t['desc']}: {r.stderr.strip()}")

# Hemen başlat
print("\nServisler başlatılıyor...")
for t in tasks:
    r = subprocess.run(
        ["schtasks", "/Run", "/TN", t["name"]],
        capture_output=True, text=True
    )
    if r.returncode == 0:
        print(f"[OK] {t['desc']} başlatıldı.")
    else:
        print(f"[HATA] {t['desc']} başlatılamadı: {r.stderr.strip()}")

print("\nBitti. Bir daha çalıştırmanıza gerek yok — oturum açıldığında otomatik başlar.")
input("Kapatmak için Enter...")
