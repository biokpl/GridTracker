#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Explorer Start Otomasyonu
=========================
MatriksIQ icindeki Explorer Listesi panelini acar ve
belirtilen explorer'larin Calistir butonlarina tiklar.

Kullanim:
  python explorer_start.pyw          # Calistir
  python explorer_start.pyw --dry    # Test modu (tiklamaz, log yazar)
  python explorer_start.pyw --debug  # Ekran goruntusu kaydeder
"""

import os, sys, time, logging, argparse
from pathlib import Path
from datetime import datetime

# ── Paket kontrol ────────────────────────────────────────────
import subprocess
for _pkg in ['pyautogui', 'pygetwindow', 'pillow']:
    try:
        __import__(_pkg.replace('pillow', 'PIL'))
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg, '-q'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

import pyautogui
import pygetwindow as gw
import pyperclip

# ── Argümanlar ───────────────────────────────────────────────
ap = argparse.ArgumentParser()
ap.add_argument('--dry',   action='store_true', help='Test modu: tiklamaz')
ap.add_argument('--debug', action='store_true', help='Ekran goruntusu kaydeder')
args = ap.parse_args()

DRY_RUN = args.dry
DEBUG   = args.debug

# ── Log ──────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
LOG_FILE   = SCRIPT_DIR / 'explorer_start.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger('explorer_start')

pyautogui.FAILSAFE = True
pyautogui.PAUSE    = 0.05


# ════════════════════════════════════════════════════════════
#  AYARLAR
# ════════════════════════════════════════════════════════════

# Explorer Listesi panelinin ekrandaki bolgesi:
# (sol_x, ust_y, genislik, yukseklik)
PANEL_REGION = (370, 62, 1088, 588)

# Calistir butonunun template dosyasi (tum satirlarda ayni gorunum)
# Template match ile her satirda tam merkez bulunur — offset hesabina gerek kalmaz
CALISTIR_TMPL = 'tmpl_calistir_btn.png'

# Yedek: template bulunamazsa kullanilacak sabit deger (kullanici olcumu: x=926)
CALISTIR_X        = 926
CALISTIR_OFFSET_Y =  35   # badge center y'den yaklasik offset (yedek icin)

# Parametreler penceresi "Bitir" butonu (tum explorer'lar icin ayni konum)
BITIR_X = 1220
BITIR_Y = 631

# Sonuclar penceresindeki export butonlari (tum explorer'lar icin ayni konum)
EXPORT_BTN1_X, EXPORT_BTN1_Y = 1086, 1244
EXPORT_BTN2_X, EXPORT_BTN2_Y = 1433, 1246

# Sonuclar bekleme parametreleri
SONUC_TIMEOUT_S = 300
SONUC_POLL_S    = 3


# ════════════════════════════════════════════════════════════
#  EXPLORER TANIMI
#  Her kayit:
#    tmpl        : Explorer Listesi'nde satiri bulmak icin template
#    name        : Log ve template dosya adlarinda kullanilir
#    filename    : Kaydedilecek Excel dosya adi
#    after_export: Oneri kapandiktan sonra yapilacak tiklamalar listesi
#                  Her eleman: (x, y, onceki_bekleme, sonraki_bekleme)
#                  onceki_bekleme: tik oncesi bekleme (s)
#                  sonraki_bekleme: tik sonrasi bekleme (s)
# ════════════════════════════════════════════════════════════
EXPLORERS = [
    {
        'tmpl':     'tmpl_atr_sonuc.png',
        'name':     'ATR_SONUC',
        'filename': 'ATR_Sonuc.xlsx',
        # Oneri kapandiktan hemen sonra: click(1395,1244), 1s bekle
        'after_export': [
            (1395, 1244, 0, 1),   # (x, y, onceki_bekleme, sonraki_bekleme)
        ],
    },
    {
        'tmpl':     'tmpl_destek_direnc.png',
        'name':     'Destek_Direnc_Seviyeleri',
        'filename': 'Destek_Direc_Seviyeleri.xlsx',
        # Oneri kapandiktan sonra: 1s bekle, click(1395,1244), 1s bekle, click(1446,75)
        'after_export': [
            (1395, 1244, 1, 1),   # 1s bekle → click(1395,1244) → 1s bekle
            (1446,   75, 0, 0),   # click(1446,75) — sonuc penceresi kapat
        ],
    },
]


# ════════════════════════════════════════════════════════════
#  YARDIMCI FONKSIYONLAR
# ════════════════════════════════════════════════════════════

def click(x, y, wait=0):
    if DRY_RUN:
        log.info(f'[DRY] Tik: ({x}, {y})  bekleme={wait}s')
    else:
        pyautogui.click(x, y)
        log.info(f'Tik: ({x}, {y})')
    if wait:
        time.sleep(wait)


def save_screenshot(label='debug'):
    if not DEBUG:
        return
    ts  = datetime.now().strftime('%H%M%S')
    out = SCRIPT_DIR / f'debug_{label}_{ts}.png'
    pyautogui.screenshot(str(out))
    log.info(f'Ekran goruntusu: {out.name}')


def bring_to_front(title_kw):
    """Basliktaki anahtar kelimeyle pencereyi one getirir."""
    if DRY_RUN:
        log.info(f'[DRY] One getir: {title_kw}')
        return True
    import ctypes, win32gui, win32con
    wins = [w for w in gw.getAllWindows() if title_kw.lower() in w.title.lower()]
    if not wins:
        log.warning(f'Pencere bulunamadi: {title_kw}')
        return False
    w    = wins[0]
    hwnd = w._hWnd
    u32  = ctypes.windll.user32
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.3)
    fg_hwnd = u32.GetForegroundWindow()
    fg_tid  = u32.GetWindowThreadProcessId(fg_hwnd, None)
    tgt_tid = u32.GetWindowThreadProcessId(hwnd, None)
    u32.AttachThreadInput(fg_tid, tgt_tid, True)
    u32.BringWindowToTop(hwnd)
    u32.SetForegroundWindow(hwnd)
    u32.AttachThreadInput(fg_tid, tgt_tid, False)
    time.sleep(0.5)
    log.info(f'One getirildi: {w.title}')
    return True


def find_template(template_file, confidence=0.80, region=None):
    """
    Template goruntusunu ekranda (veya verilen region'da) arar.
    Bulursa (x, y) merkez koordinatini dondurur, bulamazsa None.
    """
    p = SCRIPT_DIR / template_file
    if not p.exists():
        log.warning(f'Template dosyasi yok: {template_file}')
        return None
    search_region = region if region is not None else PANEL_REGION
    try:
        import cv2  # noqa
        kwargs = {'confidence': confidence}
        if search_region:
            kwargs['region'] = search_region
        center = pyautogui.locateCenterOnScreen(str(p), **kwargs)
        if center:
            log.info(f'Bulundu: {template_file} -> ({center.x}, {center.y})')
        else:
            log.warning(f'Ekranda bulunamadi: {template_file}')
        return center
    except Exception as e:
        log.debug(f'locateOnScreen ({template_file}): {e}')
        return None


# ════════════════════════════════════════════════════════════
#  ADIM 0 — Acik kalan explorer sonuc pencerelerini kapat
# ════════════════════════════════════════════════════════════

def step0_close_existing_results():
    """
    Ekranda acik kalan herhangi bir Explorer Sonuclari penceresi varsa
    ATR_SONUC template'i ile tespit edip click(1446, 75) ile kapatir.
    """
    tmpl_path = SCRIPT_DIR / 'tmpl_atr_sonuc_sonuclar.png'
    if not tmpl_path.exists():
        return

    try:
        import cv2  # noqa
        found = pyautogui.locateCenterOnScreen(str(tmpl_path), confidence=0.75)
    except Exception:
        found = None

    if not found:
        log.info('Acik sonuc penceresi yok, devam ediliyor.')
        return

    log.info(f'Acik sonuc penceresi bulundu: ({found.x}, {found.y}) — kapatiliyor...')
    click(1446, 75, wait=1)
    log.info('Sonuc penceresi kapatildi.')


# ════════════════════════════════════════════════════════════
#  ADIM 1 — Explorer Listesi panelini ac
# ════════════════════════════════════════════════════════════

def step1_open_panel():
    log.info('Adim 1: Explorer Listesi aciliyor...')

    ok = bring_to_front('IQ')
    if not ok:
        log.error('MatriksIQ bulunamadi!')
        return False

    time.sleep(0.3)
    save_screenshot('oncesi')

    # Panel zaten acik mi? (ilk explorer'in badge'ini ara)
    tmpl = SCRIPT_DIR / EXPLORERS[0]['tmpl']
    already_open = False
    if tmpl.exists():
        try:
            import cv2  # noqa
            found = pyautogui.locateCenterOnScreen(str(tmpl), confidence=0.75,
                                                   region=PANEL_REGION)
            if found:
                log.info(f'Panel zaten acik (badge bulundu: {found.x},{found.y}) — tiklanmadan geciliyor.')
                already_open = True
        except Exception:
            pass

    if not already_open:
        click(872, 42, wait=1.5)

    save_screenshot('panel_acildi')
    log.info('Panel acildi.')
    return True


# ════════════════════════════════════════════════════════════
#  ADIM 2 — Explorer satirini bul, Calistir'a tikla
# ════════════════════════════════════════════════════════════

def step2_run_explorer(explorer):
    name          = explorer['name']
    template_file = explorer['tmpl']
    log.info(f'Adim 2: {name} araniyor...')

    # Badge'i bul — satirin yaklasik y konumunu ogrenmek icin
    badge = find_template(template_file, confidence=0.80)
    if not badge:
        log.info('Dusuk confidence ile tekrar deneniyor...')
        badge = find_template(template_file, confidence=0.65)

    if not badge:
        log.error(f'{name} satirinin template\'i bulunamadi: {template_file}')
        return False

    log.info(f'{name} badge: ({badge.x}, {badge.y})')

    # Calistir butonunu badge y'sine en yakin olani bul
    btn_x, btn_y = _find_calistir_for_row(badge.y)
    log.info(f'{name} Calistir: ({btn_x}, {btn_y})')

    click(btn_x, btn_y, wait=1.5)
    log.info(f'{name} Calistir tiklandi.')
    save_screenshot(f'{name}_parametreler_acildi')
    return True


def _find_calistir_for_row(badge_y):
    """
    Explorer panelindeki tüm Çalıştır butonlarini bulur,
    badge_y'ye en yakin olani dondurur.
    Template bulunamazsa yedek koordinat hesaplar.
    """
    tmpl_path = SCRIPT_DIR / CALISTIR_TMPL
    if not tmpl_path.exists():
        log.warning(f'Calistir template yok: {CALISTIR_TMPL} — yedek koordinat kullaniliyor.')
        return CALISTIR_X, badge_y + CALISTIR_OFFSET_Y

    try:
        import cv2  # noqa
        btns = list(pyautogui.locateAllOnScreen(str(tmpl_path),
                                                confidence=0.85,
                                                region=PANEL_REGION))
    except Exception as e:
        log.warning(f'Calistir template araması hatasi: {e} — yedek koordinat kullaniliyor.')
        return CALISTIR_X, badge_y + CALISTIR_OFFSET_Y

    if not btns:
        log.warning('Calistir template ekranda bulunamadi — yedek koordinat kullaniliyor.')
        return CALISTIR_X, badge_y + CALISTIR_OFFSET_Y

    # Badge y'sine en yakin butonu sec
    closest = min(btns, key=lambda b: abs((b.top + b.height // 2) - badge_y))
    cx = closest.left + closest.width  // 2
    cy = closest.top  + closest.height // 2
    log.info(f'  {len(btns)} Calistir bulundu, en yakin: ({cx},{cy})  badge_y={badge_y}')
    return cx, cy


# ════════════════════════════════════════════════════════════
#  ADIM 3 — Parametreler penceresinde Bitir'e tikla
# ════════════════════════════════════════════════════════════

def step3_click_bitir(name):
    log.info(f'Adim 3: {name} Parametreler -> Bitir ({BITIR_X}, {BITIR_Y})...')
    click(BITIR_X, BITIR_Y, wait=0)
    log.info('Bitir tiklandi. Sonuclar penceresi bekleniyor...')
    save_screenshot(f'{name}_bitir_tiklandi')


# ════════════════════════════════════════════════════════════
#  ADIM 4 — "Explorer Sonuclari" penceresi acilana kadar bekle
# ════════════════════════════════════════════════════════════

def step4_wait_for_results(name):
    """
    Ekranda ilgili 'Explorer Sonuclari' template'i gorunene kadar bekler.
    Template yoksa 10s sabit bekleme uygular.
    """
    tmpl_file = f'tmpl_{name.lower()}_sonuclar.png'
    tmpl_path = SCRIPT_DIR / tmpl_file
    has_tmpl  = tmpl_path.exists()

    if not has_tmpl:
        log.warning(f'Sonuc pencere template\'i yok: {tmpl_file}')
        log.warning('Template olmadan 10s sabit bekleme uygulanıyor.')
        time.sleep(10)
        save_screenshot(f'{name}_sonuc_beklendi')
        return True

    log.info(f'Sonuclar penceresi bekleniyor (max {SONUC_TIMEOUT_S}s)...')
    deadline = time.time() + SONUC_TIMEOUT_S
    gecen    = 0

    while time.time() < deadline:
        try:
            import cv2  # noqa
            found = pyautogui.locateCenterOnScreen(str(tmpl_path), confidence=0.75)
            if found:
                log.info(f'Sonuclar penceresi acildi! ({found.x}, {found.y})  sure={gecen}s')
                save_screenshot(f'{name}_sonuclar_acildi')
                return True
        except Exception as e:
            log.debug(f'Tarama hatasi: {e}')

        time.sleep(SONUC_POLL_S)
        gecen += SONUC_POLL_S
        if gecen % 30 == 0:
            log.info(f'Hala bekleniyor... {gecen}s gecti.')

    log.error(f'Sonuclar penceresi {SONUC_TIMEOUT_S}s icinde acilamadi!')
    save_screenshot(f'{name}_sonuc_timeout')
    return False


# ════════════════════════════════════════════════════════════
#  ADIM 5 — Export yap, dosya kaydet, Öneri Hayır, sonrasi
# ════════════════════════════════════════════════════════════

def step5_export(explorer):
    name     = explorer['name']
    filename = explorer['filename']
    log.info(f'Adim 5: {name} export basliyor (dosya: {filename})...')

    # 1. Export butonu 1
    click(EXPORT_BTN1_X, EXPORT_BTN1_Y, wait=1)

    # 2. Export butonu 2 — dosya kayit diyalogu acar
    click(EXPORT_BTN2_X, EXPORT_BTN2_Y, wait=1)

    save_screenshot(f'{name}_dosya_diyalogu')

    # 3. Windows dosya kayit diyalogu — tam yol yaz (klasör ne olursa olsun)
    full_path = str(SCRIPT_DIR / filename)
    log.info(f'Dosya yolu yaziliyor: {full_path}')
    if not DRY_RUN:
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.2)
        pyperclip.copy(full_path)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.3)
        pyautogui.press('enter')   # Kaydet
        time.sleep(1)
        pyautogui.press('enter')   # Ustune yaz onay
        time.sleep(1)
    else:
        log.info(f'[DRY] Dosya yolu yazilacakti: {full_path} + 2x Enter')
        time.sleep(2)

    save_screenshot(f'{name}_dosya_kaydedildi')

    # 4. "Oneri" diyalogu — Hayir'a tikla
    if not _click_oneri_hayir(name):
        log.warning('Oneri diyalogu bulunamadi veya zaten kapandi.')

    # 5. Explorer tanimi icindeki after_export tiklamalari
    for (x, y, pre_wait, post_wait) in explorer.get('after_export', []):
        if pre_wait:
            time.sleep(pre_wait)
        click(x, y, wait=post_wait)

    log.info(f'{name} export tamamlandi.')
    return True


def _click_oneri_hayir(name, timeout=10):
    """
    Mavi 'Oneri' diyalogundaki 'Hayir' butonunu template ile bulup tiklar.
    """
    tmpl_path = SCRIPT_DIR / 'tmpl_oneri_hayir.png'

    if not tmpl_path.exists():
        log.warning('Oneri/Hayir template yok: tmpl_oneri_hayir.png')
        save_screenshot(f'{name}_oneri_dialog')
        return False

    log.info('Oneri diyalogu bekleniyor...')
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            import cv2  # noqa
            found = pyautogui.locateCenterOnScreen(str(tmpl_path), confidence=0.75)
            if found:
                log.info(f'Oneri/Hayir bulundu: ({found.x}, {found.y})')
                click(found.x, found.y, wait=0.5)
                save_screenshot(f'{name}_oneri_hayir_tiklandi')
                return True
        except Exception:
            pass
        time.sleep(0.5)

    save_screenshot(f'{name}_oneri_timeout')
    log.warning('Oneri diyalogu bekleme suresi doldu.')
    return False


# ════════════════════════════════════════════════════════════
#  ANA FONKSIYON
# ════════════════════════════════════════════════════════════

def run():
    log.info('=' * 55)
    log.info(f'Explorer Start basliyor  [DRY={DRY_RUN}] [DEBUG={DEBUG}]')
    log.info('=' * 55)

    # Adim 0: Onceki calistirmadan kalan acik sonuc penceresini kapat
    step0_close_existing_results()

    # Adim 1: Explorer Listesi panelini ac
    if not step1_open_panel():
        log.error('Panel acilamadi. Durduruluyor.')
        return False

    basari = 0
    for explorer in EXPLORERS:
        name = explorer['name']

        # Adim 2: Explorer listesinde Calistir'a tikla
        if not step2_run_explorer(explorer):
            log.warning(f'{name} atlandi (Calistir bulunamadi).')
            continue

        # Adim 3: Parametreler penceresinde Bitir'e tikla
        step3_click_bitir(name)

        # Adim 4: Sonuclar penceresi acilana kadar bekle
        if not step4_wait_for_results(name):
            log.warning(f'{name} sonuc penceresi acilamadi (timeout).')
            continue

        # Adim 5: Export et, Oneri kapat, sonrasi tiklama
        if step5_export(explorer):
            basari += 1
            log.info(f'{name} basariyla tamamlandi.')
        else:
            log.warning(f'{name} export adiminda sorun olustu.')

    log.info(f'Tamamlandi: {basari}/{len(EXPLORERS)} explorer tamamlandi.')
    return basari == len(EXPLORERS)


if __name__ == '__main__':
    run()
