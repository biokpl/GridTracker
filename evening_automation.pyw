#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
evening_automation.py
MatriksIQ Veri Terminali - Akşam Otomasyonu

BİST kapanışından 35 dakika sonra otomatik çalışır:
  - Normal günler  : 18:35  (kapanış 18:00 + 35 dk)
  - Arefe günleri  : 13:35  (kapanış 13:00 + 35 dk)
  - Hafta sonu / tatil : çalışmaz

Kullanım:
  python evening_automation.py            # Normal çalıştır
  python evening_automation.py --test     # DRY RUN — mouse hareketi yok
  python evening_automation.py --setup    # Task Scheduler'a iki görev ekle
"""

import os, sys, time, logging, subprocess, argparse
from pathlib import Path
from datetime import date, datetime

if sys.platform == 'win32':
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr is not None:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

for _pkg in ['pyautogui', 'pygetwindow', 'holidays']:
    try:
        __import__(_pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg])

import pyautogui
import pygetwindow as gw

pyautogui.FAILSAFE = True
pyautogui.PAUSE    = 0.05

SCRIPT_DIR = Path(__file__).parent
LOG_FILE   = SCRIPT_DIR / 'evening_automation.log'

_log_handlers = [logging.FileHandler(LOG_FILE, encoding='utf-8')]
if sys.stdout is not None:
    _log_handlers.append(logging.StreamHandler(sys.stdout))
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=_log_handlers,
)
log = logging.getLogger('EveningAuto')

DRY_RUN = False

TASK_NORMAL = 'MatriksIQ_Aksam_Otomasyonu_Normal'   # 18:35 — normal günler
TASK_AREFE  = 'MatriksIQ_Aksam_Otomasyonu_Arefe'    # 13:35 — arefe günleri

# ── Arefe günleri (2025-2028) ────────────────────────────────────────────
ARIFE_DAYS = {
    # 2025
    '2025-03-28',  # Ramazan Bayramı arefe
    '2025-06-05',  # Kurban Bayramı arefe
    '2025-10-28',  # Cumhuriyet Bayramı arefe
    # 2026
    '2026-03-19',  # Ramazan Bayramı arefe
    '2026-05-26',  # Kurban Bayramı arefe
    '2026-10-28',  # Cumhuriyet Bayramı arefe
    # 2027
    '2027-03-08',  # Ramazan Bayramı arefe
    '2027-05-15',  # Kurban Bayramı arefe
    '2027-10-28',  # Cumhuriyet Bayramı arefe
    # 2028
    '2028-02-25',  # Ramazan Bayramı arefe
    '2028-05-03',  # Kurban Bayramı arefe
    '2028-10-28',  # Cumhuriyet Bayramı arefe
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  YARDIMCI FONKSİYONLAR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def is_arefe(d=None):
    if d is None:
        d = date.today()
    return str(d) in ARIFE_DAYS


def check_skip_today():
    """Bugün çalışılmaması gerekiyorsa True döner."""
    import holidays as _holidays
    today = date.today()
    if today.weekday() >= 5:
        log.info(f'Bugün hafta sonu ({today.strftime("%A")}), otomasyon atlandı.')
        return True
    tr = _holidays.Turkey(years=today.year)
    if today in tr:
        log.info(f'Bugün resmi/dini tatil: {tr[today]} ({today}), otomasyon atlandı.')
        return True
    return False


def click(x, y, wait=0):
    if DRY_RUN:
        log.info(f'[DRY] Tık: ({x}, {y})  bekleme={wait}s')
    else:
        pyautogui.click(x, y)
        log.info(f'Tık: ({x}, {y})')
    if wait:
        time.sleep(wait)


def press(key, wait=0):
    if DRY_RUN:
        log.info(f'[DRY] Tuş: {key}  bekleme={wait}s')
    else:
        pyautogui.press(key)
        log.info(f'Tuş: {key}')
    if wait:
        time.sleep(wait)


def bring_to_front(title):
    if DRY_RUN:
        log.info(f'[DRY] Öne getir: {title}')
        return
    import ctypes, win32gui
    wins = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
    if not wins:
        log.warning(f'Pencere bulunamadı: {title}')
        return
    w = wins[0]
    hwnd = w._hWnd
    u32 = ctypes.windll.user32
    fg_hwnd = u32.GetForegroundWindow()
    fg_tid  = u32.GetWindowThreadProcessId(fg_hwnd, None)
    tgt_tid = u32.GetWindowThreadProcessId(hwnd, None)
    u32.AttachThreadInput(fg_tid, tgt_tid, True)
    u32.BringWindowToTop(hwnd)
    u32.SetForegroundWindow(hwnd)
    u32.AttachThreadInput(fg_tid, tgt_tid, False)
    time.sleep(0.5)
    log.info(f'Öne getirildi: {w.title}')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ANA OTOMASYON
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _send_notify(title, body, tag='gridtracker'):
    """automation_server /api/notify endpoint'ine POST atar."""
    import urllib.request as _ur, json as _json
    try:
        payload = _json.dumps({'title': title, 'body': body, 'tag': tag}).encode()
        req = _ur.Request('http://127.0.0.1:5050/api/notify',
                          data=payload, method='POST',
                          headers={'Content-Type': 'application/json'})
        _ur.urlopen(req, timeout=5)
        log.info(f'[Push] Bildirim gönderildi: {title}')
    except Exception as e:
        log.warning(f'[Push] Bildirim gönderilemedi: {e}')


def run(mode='normal'):
    """
    mode='normal' → 18:35 görevi tarafından tetiklenir (arefe günü ise çıkar)
    mode='arefe'  → 13:35 görevi tarafından tetiklenir (arefe günü değilse çıkar)
    """
    log.info('══════════════════════════════════════════')
    log.info('  AKSAM OTOMASYONU BASLIYOR')
    log.info('══════════════════════════════════════════')

    if check_skip_today():
        return

    today_arefe = is_arefe()

    if mode == 'normal' and today_arefe:
        log.info('Bugün arefe günü — 13:35 görevi çalışacak, bu görev (18:35) atlandı.')
        return
    if mode == 'arefe' and not today_arefe:
        log.info('Bugün arefe günü değil — bu görev (13:35) atlandı.')
        return

    log.info(f'Mod: {"AREFE (13:35)" if today_arefe else "NORMAL (18:35)"}')

    # ── Adım 1: MatriksIQ'yu öne getir ─────────────────────
    bring_to_front('MatriksIQ')

    # ── Adım 2: İşlemler ────────────────────────────────────
    click(2735, 903, wait=1)
    click(667,  41,  wait=3)
    click(2152, 339, wait=1)

    click(3018, 284, wait=2)
    press('1',  wait=1)
    press('enter', wait=2)
    click(2592, 737, wait=1)

    click(2412, 341)

    click(3018, 284, wait=2)
    press('2',  wait=1)
    press('enter', wait=2)
    click(2592, 737, wait=1)

    click(3220, 256, wait=1)
    click(5106, 12,  wait=1)
    click(2681, 753, wait=0.5)

    # ── Adım 3: Excel verilerini işle ve Firebase'e yaz ─────
    log.info('Excel verileri işleniyor ve Firebase güncelleniyor...')
    grid_script = SCRIPT_DIR / 'grid_tracker_service.pyw'
    if grid_script.exists():
        result = subprocess.run(
            [sys.executable, str(grid_script), '--now'],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            cwd=str(SCRIPT_DIR)
        )
        if result.returncode == 0:
            log.info('grid_tracker_service.py --now tamamlandı ✓')
        else:
            log.warning(f'grid_tracker_service.py hatası: {result.stderr[:200]}')
    else:
        log.warning(f'grid_tracker_service.py bulunamadı: {grid_script}')

    log.info('══════════════════════════════════════════')
    log.info('  AKSAM OTOMASYONU TAMAMLANDI')
    log.info('══════════════════════════════════════════')
    _send_notify('🌙 Akşam Otomasyonu Tamamlandı', 'Günlük veriler işlendi ve kaydedildi.', 'evening-done')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TASK SCHEDULER KURULUM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def setup_tasks():
    python = str(Path(sys.executable).parent / 'pythonw.exe')
    script = str(Path(__file__).resolve())

    tasks = [
        (TASK_NORMAL, '18:35', 'normal'),
        (TASK_AREFE,  '13:35', 'arefe'),
    ]

    # Eski generic isimli görev varsa temizle (tekrar eklenmesin)
    for old in ['MatriksIQ_Aksam_Otomasyonu', 'GridBotTracker']:
        subprocess.run(f'schtasks /Delete /TN "{old}" /F',
                       shell=True, capture_output=True)

    for name, st, mode in tasks:
        # Varsa sil
        subprocess.run(
            f'schtasks /Delete /TN "{name}" /F',
            shell=True, capture_output=True
        )
        cmd = (
            f'schtasks /Create /TN "{name}" '
            f'/TR "\\"{python}\\" \\"{script}\\" --mode {mode}" '
            f'/SC WEEKLY /D MON,TUE,WED,THU,FRI '
            f'/ST {st} /F'
        )
        result = subprocess.run(cmd, shell=True, capture_output=True,
                                text=True, encoding='utf-8', errors='replace')
        if result.returncode == 0:
            log.info(f'Görev oluşturuldu: {name}  ({st}, mod={mode})')
        else:
            log.error(f'Görev hatası [{name}]: {result.stdout}{result.stderr}')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BAŞLANGIÇ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MatriksIQ Akşam Otomasyonu')
    parser.add_argument('--test',  action='store_true',
                        help='Adımları logla, mouse hareketi yapma')
    parser.add_argument('--setup', action='store_true',
                        help='Task Scheduler görevlerini oluştur (18:35 + 13:35)')
    parser.add_argument('--mode', choices=['normal', 'arefe'], default='normal',
                        help='normal=18:35 görevi, arefe=13:35 görevi')
    args = parser.parse_args()

    if args.setup:
        setup_tasks()
        sys.exit(0)

    if args.test:
        DRY_RUN = True
        log.info('TEST MODU — Mouse hareketi yok')

    try:
        run(mode=args.mode)
    except KeyboardInterrupt:
        log.info('Kullanıcı tarafından durduruldu (Ctrl+C)')
    except Exception as e:
        log.exception(f'Beklenmeyen hata: {e}')
        sys.exit(1)
