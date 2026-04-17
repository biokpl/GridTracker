#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recapture_templates.py
======================
Explorer Listesi panelindeki ATR_SONUC ve Destek_Direc_Seviyeleri satirlarinin
badge template'lerini yeniden yakalar ve kaydeder.

Kullanim:
  1. MatriksIQ acik olmali ve Explorer Listesi gorünür olmali.
  2. python recapture_templates.py --scan        # Panel satirlarini tara, koordinatlari goster
  3. python recapture_templates.py --capture     # Template'leri yakala ve kaydet
  4. python recapture_templates.py --test        # Kaydedilen template'leri test et
"""

import sys, time, argparse
from pathlib import Path

import subprocess
for _pkg in ['pyautogui', 'opencv-python', 'pillow']:
    try:
        __import__(_pkg.replace('opencv-python', 'cv2').replace('pillow', 'PIL'))
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg, '-q'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

import pyautogui
import cv2
import numpy as np
from PIL import Image

SCRIPT_DIR   = Path(__file__).parent
PANEL_REGION = (370, 62, 1088, 588)   # (left, top, width, height)
BADGE_REGION = (370, 62, 380, 588)    # sol yarisi — badge araması için

# Template'lerin kaydedileceği dosya adları
TEMPLATES = {
    'ATR_SONUC':              'tmpl_atr_sonuc.png',
    'Destek_Direc_Seviyeleri': 'tmpl_destek_direnc.png',
}

# Her satir için badge crop parametreleri (ikon + isim)
# (x_offset_from_row_left, y_offset_from_row_center, width, height)
# Bu değerler --scan çalıştırdıktan sonra gözlemle güncellenir
CROP_PARAMS = {
    # row_center_y'ye göre: center_y - half_h .. center_y + half_h
    # crop_x: panelin solundan (370) itibaren
    'crop_x'    : 370,   # panel sol kenarı
    'crop_w'    : 350,   # sağa doğru genişlik (ikon + isim yazısını kapsar)
    'half_h'    : 22,    # satır merkezinin üstünde/altında kaç px
}


def open_panel():
    """Explorer Listesi panelini açar (872, 42)."""
    print('Explorer Listesi açılıyor (872, 42)...')
    pyautogui.click(872, 42)
    time.sleep(1.5)


def take_panel_screenshot():
    """Panel bölgesinin ekran görüntüsünü alır."""
    left, top, w, h = PANEL_REGION
    shot = pyautogui.screenshot(region=(left, top, w, h))
    return shot, left, top


def scan_rows():
    """
    Panel ekran görüntüsünü alır, yatay satır bölgelerini gösterir
    ve debug_scan.png olarak kaydeder.
    """
    shot, left, top = take_panel_screenshot()
    out = SCRIPT_DIR / 'debug_scan.png'
    shot.save(str(out))
    print(f'\nPanel ekran görüntüsü kaydedildi: {out.name}')
    print(f'Panel koordinatları: left={left}, top={top}')
    print(f'Görüntü boyutu: {shot.width} x {shot.height} px')
    print()
    print('Bu görüntüyü inceleyerek satır merkez y-koordinatlarını belirleyin.')
    print('Ardından --capture ile template kaydedin.')
    return shot, left, top


def find_rows_by_color(shot, left, top):
    """
    Panel görüntüsünde koyu arka planlı satırları bulmaya çalışır.
    Her yatay bölgenin ortalama rengini analiz eder.
    """
    arr = np.array(shot.convert('RGB'))
    h, w = arr.shape[:2]

    # Her y satırının ortalama parlaklığını hesapla
    row_brightness = arr.mean(axis=(1, 2))

    # Görece daha açık (yani satır içeriği olan) bölgeleri bul
    threshold = row_brightness.mean() * 0.95
    in_row    = False
    rows      = []
    row_start = 0

    for y in range(h):
        bright = row_brightness[y]
        if not in_row and bright > threshold:
            in_row    = True
            row_start = y
        elif in_row and bright <= threshold:
            in_row = False
            mid    = (row_start + y) // 2
            rows.append(mid)

    if in_row:
        mid = (row_start + h) // 2
        rows.append(mid)

    print(f'Olası satır merkez y-koordinatları (panel içi, 0=panel üstü):')
    for i, y in enumerate(rows):
        screen_y = top + y
        print(f'  Satır {i+1}: panel_y={y}  →  screen_y={screen_y}')

    return rows


def capture_templates(row_ys_screen):
    """
    Verilen screen y koordinatlarından badge template'lerini yakalar ve kaydeder.
    row_ys_screen: [destek_screen_y, atr_screen_y]  — sıralı (küçük y = üst satır)
    """
    cp      = CROP_PARAMS
    names   = ['Destek_Direc_Seviyeleri', 'ATR_SONUC']
    files   = ['tmpl_destek_direnc.png', 'tmpl_atr_sonuc.png']

    if len(row_ys_screen) != 2:
        print(f'HATA: 2 satır y-koordinatı bekleniyor, {len(row_ys_screen)} verildi.')
        sys.exit(1)

    for i, screen_y in enumerate(row_ys_screen):
        x      = cp['crop_x']
        y1     = screen_y - cp['half_h']
        y2     = screen_y + cp['half_h']
        region = (x, y1, cp['crop_w'], y2 - y1)

        print(f'\n{names[i]} yakalanıyor: region={region}')
        shot = pyautogui.screenshot(region=region)

        # Yedek olarak eski dosyayı sakla
        out_path = SCRIPT_DIR / files[i]
        if out_path.exists():
            bak = out_path.with_suffix('.bak.png')
            out_path.rename(bak)
            print(f'  Eski template yedeklendi: {bak.name}')

        shot.save(str(out_path))
        print(f'  Kaydedildi: {out_path.name}  ({shot.width}x{shot.height} px)')


def test_templates():
    """
    Kaydedilen template'leri BADGE_REGION içinde arar ve sonuçları raporlar.
    """
    print('\nTemplate test ediliyor...')
    for name, fname in TEMPLATES.items():
        p = SCRIPT_DIR / fname
        if not p.exists():
            print(f'  [{name}] DOSYA YOK: {fname}')
            continue
        try:
            center = pyautogui.locateCenterOnScreen(str(p), confidence=0.75,
                                                    region=BADGE_REGION)
            if center:
                print(f'  [{name}] BULUNDU: ({center.x}, {center.y})  ✓')
            else:
                print(f'  [{name}] BULUNAMADI (confidence=0.75, BADGE_REGION)  ✗')
                # Geniş bölgede dene
                center2 = pyautogui.locateCenterOnScreen(str(p), confidence=0.65,
                                                         region=PANEL_REGION)
                if center2:
                    print(f'           PANEL_REGION\'da bulundu: ({center2.x}, {center2.y})'
                          f'  — badge bölgesi dışında!')
        except Exception as e:
            print(f'  [{name}] HATA: {e}')


def interactive_capture():
    """
    Kullanıcıdan satır y-koordinatlarını alarak template yakalar.
    """
    print('\n=== Etkileşimli Template Yakalama ===')
    print('MatriksIQ açık ve Explorer Listesi görünür olmalı.')
    print()

    try:
        destek_y = int(input('Destek_Direc_Seviyeleri satırı merkez y-koordinatı (screen): '))
        atr_y    = int(input('ATR_SONUC satırı merkez y-koordinatı (screen): '))
    except (ValueError, EOFError):
        print('Geçersiz giriş.')
        sys.exit(1)

    capture_templates([destek_y, atr_y])
    print('\nTemplate yakalama tamamlandı.')
    test_templates()


# ─── Argüman işleme ──────────────────────────────────────────
ap = argparse.ArgumentParser(description='Explorer badge template yakalayıcı')
ap.add_argument('--scan',     action='store_true', help='Paneli tara, satır y koordinatlarını bul')
ap.add_argument('--capture',  nargs=2, type=int, metavar=('DESTEK_Y', 'ATR_Y'),
                help='Verilen screen y koordinatlarından template yakala')
ap.add_argument('--interactive', action='store_true', help='Etkileşimli mod')
ap.add_argument('--test',     action='store_true', help='Mevcut template\'leri test et')
ap.add_argument('--open-panel', action='store_true', help='Explorer Listesi panelini aç')
args = ap.parse_args()

if args.open_panel:
    open_panel()

if args.scan:
    shot, left, top = scan_rows()
    find_rows_by_color(shot, left, top)
    print('\ndebug_scan.png dosyasını inceleyerek satır y-koordinatlarını belirleyin.')
    print('Ardından:  python recapture_templates.py --capture DESTEK_Y ATR_Y')

elif args.capture:
    destek_y, atr_y = args.capture
    capture_templates([destek_y, atr_y])
    test_templates()

elif args.interactive:
    interactive_capture()

elif args.test:
    test_templates()

else:
    ap.print_help()
