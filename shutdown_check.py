#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
PC Kapatma Kontrolü - GridTracker
=================================
Görev Zamanlayıcı'dan her gün 09:20'de çalışır.
Eğer bugün hafta sonu VEYA Türkiye resmi/dini tatili ise PC'yi kapatır.
Arife günleri (BIST yarım gün): PC açık kalır, otomasyon çalışır.

Kullanım:
  python shutdown_check.py        # Normal çalışma (gerekirse kapat)
  python shutdown_check.py --force # Zorla kapat (debug)
  python shutdown_check.py --show  # Sadece durumu göster, kapatma

Görev Zamanlayıcı ayarı:
  - Tetikleyici: Her gün 09:20
  - Program: pythonw.exe
  - Bağımsız değişken: "C:\Users\BioCSI\CLAUDE\GridTracker\shutdown_check.py"
"""

import os, sys, logging
from pathlib import Path

# ── Logging ─────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent
LOG_FILE = LOG_DIR / 'shutdown_check.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger('shutdown')

# ── Arife günleri (2025-2028) ───────────────────────────────────────────
# Arife günleri: BIST yarım gün açık, PC açık kalır, otomasyon çalışır
AREFE_DAYS = {
    '2025-03-28',  # Ramazan Bayramı arefe
    '2025-06-05',  # Kurban Bayramı arefe
    '2025-10-28',  # Cumhuriyet Bayramı arefe
    '2026-03-19',  # Ramazan Bayramı arefe
    '2026-05-26',  # Kurban Bayramı arefe
    '2026-10-28',  # Cumhuriyet Bayramı arefe
    '2027-03-08',  # Ramazan Bayramı arefe
    '2027-05-15',  # Kurban Bayramı arefe
    '2027-10-28',  # Cumhuriyet Bayramı arefe
    '2028-02-25',  # Ramazan Bayramı arefe
    '2028-05-03',  # Kurban Bayramı arefe
    '2028-10-28',  # Cumhuriyet Bayramı arefe
}

# ── Tatil Kontrolü ──────────────────────────────────────────────────────

def is_working_day(d=None):
    """
    Bugün çalışma günü mü?
    - Hafta sonu (Cumartesi/Pazar) → False (PC kapanır)
    - Resmi/Dini tatil → False (PC kapanır)
    - Arife günü (BIST yarım gün) → True (PC açık kalır, otomasyon çalışır)
    """
    from datetime import date
    import holidays as _holidays

    if d is None:
        d = date.today()

    # Hafta sonu kontrolü (5=Cumartesi, 6=Pazar)
    if d.weekday() >= 5:
        log.info(f'Hafta sonu tespit edildi: {d.strftime("%A")} ({d})')
        return False

    # Türkiye resmi/dini tatillerini kontrol et
    tr_holidays = _holidays.Turkey(years=d.year)
    if d in tr_holidays:
        log.info(f'Resmi/Dini tatil tespit edildi: {tr_holidays[d]} ({d})')
        return False

    # Arife günleri kontrolü (yarım gün - BIST açık)
    if d.strftime('%Y-%m-%d') in AREFE_DAYS:
        log.info(f'Arife gunu tespit edildi: {d} - BIST yarim gun, PC ACIK KALACAK')
        return True  # Arefe = çalışma günü, PC kapanmaz

    return True


def shutdown_pc(reason=''):
    """PC'yi kapat."""
    log.info(f'PC KAPATILIYOR: {reason}')
    try:
        os.system('shutdown /s /t 60 /c "GridTracker otomasyonu - Bilgisayar 60 saniye içinde kapanacak."')
        log.info('Shutdown komutu gönderildi (60sn gecikme)')
        return True
    except Exception as e:
        log.error(f'Shutdown hatası: {e}')
        return False


def cancel_shutdown():
    """Planlanan shutdown'u iptal et."""
    try:
        os.system('shutdown /a')
        log.info('Shutdown iptal edildi')
        return True
    except Exception as e:
        log.error(f'Shutdown iptal hatası: {e}')
        return False


# ── Main ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='PC Kapatma Kontrolü')
    parser.add_argument('--force', action='store_true', help='Zorla kapat')
    parser.add_argument('--show', action='store_true', help='Sadece durumu göster')
    parser.add_argument('--cancel', action='store_true', help='Planlanan shutdown\'u iptal et')
    args = parser.parse_args()

    log.info('══════════════════════════════════════════')
    log.info('  PC KAPATMA KONTROLÜ')
    log.info('══════════════════════════════════════════')

    # İptal modu
    if args.cancel:
        cancel_shutdown()
        sys.exit(0)

    # Show modu - sadece durumu göster
    if args.show:
        today = __import__('datetime').date.today()
        working = is_working_day(today)
        print(f'Bugün ({today}): {"Çalışma günü - PC KAPATILMAYACAK" if working else "Tatil/Hafta sonu - PC KAPATILACAK"}')
        sys.exit(0)

    # Normal çalışma
    today = __import__('datetime').date.today()

    if is_working_day(today) and not args.force:
        log.info(f'Bugün ({today.strftime("%A")}) çalışma günü - shutdown atlandı.')
        sys.exit(0)

    if args.force:
        shutdown_pc(f'--force baypası ile: {today}')
    else:
        shutdown_pc(f'Tatil/Hafta sonu: {today}')