#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor_off.pyw
LS49AG95 fiziksel monitörünü sabah otomasyonundan önce DDC/CI ile kapat.
09:11'de çalışır, iş günleri + arife günleri (hafta sonu ve tatillerde atlar).

Kullanım:
  pythonw monitor_off.pyw          # Monitörü kapat
  python  monitor_off.pyw --setup  # Task Scheduler görevini oluştur (09:11)
  python  monitor_off.pyw --test   # Tatil kontrolünü atla, direkt kapat (test)
"""

import sys, time, logging, subprocess, argparse
from pathlib import Path
from datetime import date

# ── Bağımlılıkları otomatik yükle ──────────────────────────────────────
for _pkg in ['monitorcontrol', 'holidays']:
    try:
        __import__(_pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg])

# ── Loglama ────────────────────────────────────────────────────────────
LOG_FILE = Path(__file__).parent / 'monitor_off.log'
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    encoding='utf-8',
)
log = logging.getLogger(__name__)

TASK_NAME  = 'MatriksIQ_Monitor_Kapat'
TASK_TIME  = '09:11'
SCRIPT_DIR = Path(__file__).parent

# Hedef monitör model adı (kısmi, büyük/küçük harf duyarsız)
# Sanal monitörler DDC/CI desteklemediğinden monitorcontrol onları görmez.
TARGET_MODEL = 'LS49AG95'


# ── Tatil kontrolü ─────────────────────────────────────────────────────
def check_skip_today():
    """
    Bugün hafta sonu veya Türkiye resmi/dini tatili ise True döner.
    Arife günleri tatil sayılmaz — sabah otomasyonu arife günleri de çalışır.
    """
    import holidays as _holidays
    today = date.today()
    if today.weekday() >= 5:   # 5=Cumartesi, 6=Pazar
        log.info(f'Bugün hafta sonu ({today.strftime("%A")}), atlandı.')
        return True
    tr = _holidays.Turkey(years=today.year)
    if today in tr:
        log.info(f'Bugün resmi/dini tatil: {tr[today]} ({today}), atlandı.')
        return True
    return False


# ── Monitör kapatma ────────────────────────────────────────────────────
def turn_off_monitor():
    """
    DDC/CI üzerinden fiziksel monitörü kapat.
    Sanal monitörler DDC/CI desteklemez; sadece gerçek donanım etkilenir.
    """
    from monitorcontrol import get_monitors, PowerMode

    monitors = list(get_monitors())
    log.info(f'DDC/CI ile bulunan monitör sayısı: {len(monitors)}')

    if not monitors:
        log.warning('Hiç DDC/CI monitörü bulunamadı.')
        return

    turned_off = False
    for i, monitor in enumerate(monitors):
        try:
            with monitor:
                # Model adını oku (desteklenmiyorsa boş döner)
                try:
                    caps = monitor.get_vcp_capabilities()
                    model = caps.get('model', '') if isinstance(caps, dict) else ''
                except Exception:
                    model = ''

                log.info(f'Monitör {i}: model={model!r}')

                # Hedef model eşleşiyorsa VEYA model okunamıyorsa kapat
                # (sanal monitörler DDC/CI'ya hiç dahil olmaz, güvenli)
                if TARGET_MODEL.lower() in model.lower() or not model:
                    monitor.set_power_mode(PowerMode.off_soft)
                    log.info(f'Monitör {i} ({model or "model okunamadı"}) kapatıldı '
                             f'(PowerMode.off_soft).')
                    turned_off = True
                    break
        except Exception as e:
            log.warning(f'Monitör {i} DDC/CI hatası: {e}')

    if not turned_off:
        log.warning('Hedef monitör kapatılamadı.')


# ── Task Scheduler kurulum ─────────────────────────────────────────────
def setup_task():
    """Task Scheduler'a MON-FRI 09:11 görevi ekle."""
    python = str(Path(sys.executable).parent / 'pythonw.exe')
    script = str(SCRIPT_DIR / 'monitor_off.pyw')

    # Varsa sil
    subprocess.run(
        f'schtasks /Delete /TN "{TASK_NAME}" /F',
        shell=True, capture_output=True
    )

    # Yeni görev oluştur
    cmd = (
        f'schtasks /Create /TN "{TASK_NAME}" '
        f'/TR "\\"{python}\\" \\"{script}\\"" '
        f'/SC WEEKLY /D MON,TUE,WED,THU,FRI '
        f'/ST {TASK_TIME} /F'
    )
    result = subprocess.run(
        cmd, shell=True, capture_output=True,
        text=True, encoding='utf-8', errors='replace'
    )
    if result.returncode == 0:
        print(f'[OK] Görev oluşturuldu: "{TASK_NAME}" @ {TASK_TIME} (Pzt-Cum)')
    else:
        print(f'[HATA] {result.stdout}{result.stderr}')


# ── Ana akış ──────────────────────────────────────────────────────────
def run(skip_check=False):
    log.info('══════════════════════════════════════════')
    log.info('  MONİTÖR KAPATMA BAŞLIYOR')
    log.info('══════════════════════════════════════════')

    if not skip_check and check_skip_today():
        return

    # PC yeni açıldıysa sürücülerin yüklenmesi için kısa bekle
    log.info('Sistem hazır olana kadar 20 saniye bekleniyor...')
    time.sleep(20)

    turn_off_monitor()
    log.info('Tamamlandı.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='LS49AG95 monitörünü kapat')
    parser.add_argument('--setup', action='store_true',
                        help='Task Scheduler görevini oluştur (09:11, Pzt-Cum)')
    parser.add_argument('--test', action='store_true',
                        help='Tatil kontrolünü atla, direkt kapat')
    args = parser.parse_args()

    if args.setup:
        setup_task()
    else:
        run(skip_check=args.test)
