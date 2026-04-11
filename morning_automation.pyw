#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
morning_automation.py
MatriksIQ Veri Terminali - Sabah Otomasyonu
Her iş gününde 09:15'te otomatik çalışır.

Kullanım:
  python morning_automation.py          # Normal çalıştır
  python morning_automation.py --test   # Adımları logla, mouse hareketi yok
"""

import os, sys, time, logging, subprocess, argparse, configparser
from pathlib import Path

# Windows terminali UTF-8 olarak ayarla (pythonw.exe'de stdout/stderr None olabilir)
if sys.platform == 'win32':
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr is not None:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ── Bağımlılıkları otomatik yükle ──────────────────────────────────────
for _pkg in ['pyautogui', 'pygetwindow', 'pyperclip', 'pynput', 'holidays']:
    try:
        __import__(_pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg])

import pyautogui
import pygetwindow as gw
import pyperclip
from pynput.keyboard import Key, Controller as KeyboardController
_kb = KeyboardController()

# ── DevTools Console JS kodları ────────────────────────────────────────

# Google Messages sol panelinde "INFOYATIRIM" konuşmasını bulup tıklar.
# TreeWalker ile tüm metin düğümlerini tarar, bulunan elementin
# tıklanabilir üst elemanına (LI, role=option/listitem, tabIndex≥0) çıkar.
_JS_CLICK_INFOYATIRIM = (
    "copy((function(){"
    "var tw=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,null);"
    "var n;"
    "while((n=tw.nextNode())){"
    "if(n.nodeValue.trim()==='INFOYATIRIM'){"
    "var el=n.parentElement;"
    "for(var i=0;i<8;i++){"
    "if(!el||el===document.body)break;"
    "if(el.tagName==='LI'||el.getAttribute('role')==='option'||"
    "el.getAttribute('role')==='listitem'||el.tabIndex>=0)"
    "{el.click();return 'ok:'+el.tagName;}"
    "el=el.parentElement;}"
    "n.parentElement.click();return 'ok:fallback';}}"
    "return 'not_found';"
    "})())"
)

# Google Messages "Mobil veri kullanılıyor" banner'ını kapatır.
# Banner içindeki mat-icon 'close' butonunu ya da aria-label="Kapat" butonunu tıklar.
_JS_DISMISS_BANNER = (
    "copy((function(){"
    "var tw=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,null);"
    "var n;"
    "while((n=tw.nextNode())){"
    "if(n.nodeValue.includes('Mobil veri')||n.nodeValue.includes('mobile data')){"
    "var el=n.parentElement;"
    "for(var i=0;i<8;i++){"
    "if(!el||el===document.body)break;"
    "var btns=el.querySelectorAll('button,[role=\"button\"]');"
    "for(var b of btns){"
    "var ic=b.querySelector('mat-icon');"
    "if(ic&&ic.textContent.trim()==='close'){b.click();return 'ok:mat-icon';}"
    "if(b.getAttribute('aria-label')==='Kapat'||b.getAttribute('aria-label')==='Close'||b.textContent.trim()==='×'){b.click();return 'ok:aria';}"
    "}"
    "el=el.parentElement;}}"
    "}"
    "return 'no_banner';"
    "})())"
)

# Sayfa metninde "123456 B001" formatı aranır, son eşleşmenin 6 haneli
# sayısı DevTools copy() fonksiyonu ile clipboard'a yazılır.
_JS_EXTRACT_B001 = (
    "copy((function(){"
    "var m=[...document.body.innerText.matchAll(/(\\d{6})\\s+B001/g)];"
    "return m.length?m[m.length-1][1]:'';"
    "})())"
)

# ── Güvenlik ayarları ───────────────────────────────────────────────────
pyautogui.FAILSAFE = True   # Mouse'u sol üst köşeye çekince script durur
pyautogui.PAUSE    = 0.05   # Her pyautogui çağrısı arasında 50ms

# ── Log ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
LOG_FILE   = SCRIPT_DIR / 'morning_automation.log'

_log_handlers = [logging.FileHandler(LOG_FILE, encoding='utf-8')]
if sys.stdout is not None:
    _log_handlers.append(logging.StreamHandler(sys.stdout))
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=_log_handlers,
)
log = logging.getLogger('MorningAuto')

DESKTOP  = Path.home() / 'Desktop'
DRY_RUN   = False   # --test argümanı ile True olur
FORCE_NOW = False   # --now argümanı ile True olur (hafta sonu/tatil atla)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  YARDIMCI FONKSİYONLAR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def click(x, y, double=False, wait=0):
    """Tek veya çift sol tıklama; wait saniye bekler."""
    if DRY_RUN:
        log.info(f'[DRY] {"Çift tık" if double else "Tık"}: ({x}, {y})  bekleme={wait}s')
    else:
        if double:
            pyautogui.doubleClick(x, y)
            log.info(f'Çift tık: ({x}, {y})')
        else:
            pyautogui.click(x, y)
            log.info(f'Tık: ({x}, {y})')
    if wait:
        time.sleep(wait)


def press(key, wait=0, physical=False):
    """
    Klavye tuşuna basar.
    physical=True → pynput ile scan-code seviyesinde gönderir
                     (donanım makrolarını tetiklemek için).
    """
    if DRY_RUN:
        log.info(f'[DRY] Tuş: {key}  physical={physical}  bekleme={wait}s')
    else:
        if physical:
            # pynput scan-code gönderir — yazılım + donanım makrolarını tetikler
            k = getattr(Key, key, key)
            _kb.press(k)
            time.sleep(0.05)
            _kb.release(k)
            log.info(f'Tuş (fiziksel): {key}')
        else:
            pyautogui.press(key)
            log.info(f'Tuş: {key}')
    if wait:
        time.sleep(wait)


def hotkey(*keys):
    """Klavye kombinasyonu (örn. ctrl+c)."""
    if DRY_RUN:
        log.info(f'[DRY] Kısayol: {"+".join(keys)}')
    else:
        pyautogui.hotkey(*keys)
        log.info(f'Kısayol: {"+".join(keys)}')
    time.sleep(0.2)


def wait_for_window(title, timeout=90, poll=1.0):
    """Başlıkta 'title' geçen pencere açılana kadar bekler."""
    log.info(f'Pencere bekleniyor: "{title}" (max {timeout}s)')
    if DRY_RUN:
        log.info(f'[DRY] Pencere bulunmuş sayıldı: {title}')
        return None
    t0 = time.time()
    while time.time() - t0 < timeout:
        wins = gw.getWindowsWithTitle(title)
        if wins:
            log.info(f'Pencere bulundu: {wins[0].title}')
            return wins[0]
        time.sleep(poll)
    raise TimeoutError(f'"{title}" penceresi {timeout}s içinde açılmadı')


def close_vivaldi():
    """
    Vivaldi'yi kapatır:
    1. Vivaldi penceresine tıklayarak gerçek klavye odağını alır
    2. Ctrl+W ile aktif sekmeyi kapatır (oturum geçmişine Messages yazılmasın)
    3. WM_CLOSE ile pencereyi kapatır
    """
    if DRY_RUN:
        log.info('[DRY] Vivaldi sekmesi + penceresi kapatıldı')
        return
    import win32gui, win32con
    wins = [w for w in gw.getAllWindows() if 'vivaldi' in w.title.lower()]
    if not wins:
        log.warning('Vivaldi penceresi bulunamadı — zaten kapalı olabilir')
        return
    w = wins[0]
    # Önce öne getir
    bring_to_front('Vivaldi')
    time.sleep(0.5)
    # Sekme çubuğu bölgesine tıkla — gerçek klavye odağı için
    tab_x = w.left + w.width // 2
    tab_y = w.top + 20   # başlık çubuğu / sekme alanı
    pyautogui.click(tab_x, tab_y)
    time.sleep(0.4)
    pyautogui.hotkey('ctrl', 'w')   # Aktif sekmeyi kapat
    log.info('Vivaldi aktif sekmesi Ctrl+W ile kapatıldı')
    time.sleep(1.5)
    # Pencereyi kapat
    wins = [w for w in gw.getAllWindows() if 'vivaldi' in w.title.lower()]
    if wins:
        hwnd = wins[0]._hWnd
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        log.info('Vivaldi WM_CLOSE gönderildi')
    time.sleep(1.5)


def _find_child_button(parent_hwnd, button_text):
    """Ebeveyn penceredeki belirli metinli butonu bulur."""
    import win32gui
    result = [None]
    def _cb(hwnd, _):
        if win32gui.GetWindowText(hwnd) == button_text:
            result[0] = hwnd
            return False   # aramayı durdur
        return True
    try:
        win32gui.EnumChildWindows(parent_hwnd, _cb, None)
    except Exception:
        pass
    return result[0]


def _locate_template(template_name, confidence=0.75, region=None):
    """Template görüntüsünü ekranda arar, bulamazsa None döner.
    region=(x, y, w, h) verilirse yalnızca o alanda arar."""
    p = SCRIPT_DIR / template_name
    if not p.exists():
        return None
    try:
        import cv2  # noqa
        kwargs = {'confidence': confidence}
        if region:
            kwargs['region'] = region
        center = pyautogui.locateCenterOnScreen(str(p), **kwargs)
        return center
    except Exception as e:
        log.debug(f'locateOnScreen ({template_name}): {e}')
        return None


def handle_dialogs():
    """
    click(2725, 903) sonrası çıkan MatriksIQ dialog'larını yönetir:
      - Uyarı  → 'Eski Versiyon İle Devam Et' (template ile) — birden fazla olabilir
      - Bilgi  → 'Tamam' — önce template (dar bölge), sonra mouse+offset yedek yöntemi

    Bilgi penceresi MatriksIQ tarafından mouse imlecinin yanına açılır.
    Analiz sonucu: Tamam butonu ≈ son_uyari_tiklama + (-12, +43) piksel uzağında.
    """
    if DRY_RUN:
        log.info('[DRY] Dialog döngüsü: Uyarı×N → Bilgi → Tamam')
        return

    log.info('Dialog döngüsü başladı...')
    uyari_sayisi = 0
    son_uyari_pos = None   # Son Uyarı tıklaması — Bilgi offset hesabı için

    for attempt in range(30):
        # ── Uyarı: template ile bul ve tıkla ──────────────────
        center = _locate_template('uyari_eski_btn.png', confidence=0.75)
        if center:
            pyautogui.click(center)
            log.info(f'Uyarı #{attempt+1}: "Eski Versiyon İle Devam Et" tıklandı @ {center}')
            son_uyari_pos = center
            uyari_sayisi += 1
            time.sleep(5)
            continue

        # ── Bilgi: Tamam butonunu tıkla ───────────────────────
        # Kural: Bilgi penceresi son Uyarı tıklamasının hemen altında açılır.
        # Tamam X = mouse X (değişmez), Tamam Y = mouse Y + 100
        if uyari_sayisi > 0:
            mx, my = pyautogui.position()
            tamam_x = mx
            tamam_y = my + 100
            pyautogui.click(tamam_x, tamam_y)
            log.info(f'Bilgi: "Tamam" tıklandı @ ({tamam_x},{tamam_y})  [mouse=({mx},{my})+100]')
            time.sleep(1.0)
            return

        time.sleep(0.5)

    log.warning('Dialog döngüsü max iterasyona ulaştı')


def bring_to_front(title):
    """Başlıkta 'title' geçen pencereyi boyutunu değiştirmeden öne getirir."""
    if DRY_RUN:
        log.info(f'[DRY] Öne getir: {title}')
        return None
    import ctypes, win32gui, win32con
    wins = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
    if not wins:
        log.warning(f'Pencere bulunamadi: {title}')
        return None
    w = wins[0]
    hwnd = w._hWnd
    u32 = ctypes.windll.user32
    # Minimize edilmişse önce normal boyuta getir
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
    return w


def minimize_window(title):
    """Başlıkta 'title' geçen pencereyi minimize eder."""
    if DRY_RUN:
        return
    import win32gui, win32con
    wins = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
    if wins:
        win32gui.ShowWindow(wins[0]._hWnd, win32con.SW_MINIMIZE)
        log.info(f'Minimize edildi: {wins[0].title}')


def open_shortcut(path, required=True):
    """Uygulamayı başlatır. required=True ise dosya yoksa çıkar."""
    if DRY_RUN:
        log.info(f'[DRY] Çalıştırılıyor: {path}')
        return True
    p = Path(path)
    if not p.exists():
        if required:
            log.error(f'Dosya bulunamadı: {path}')
            sys.exit(1)
        else:
            log.warning(f'Dosya bulunamadı (atlanıyor): {path}')
            return False
    log.info(f'Çalıştırılıyor: {path}')
    # Explorer ile çift tıklamaya en yakın yöntem:
    # cwd = uygulamanın kendi klasörü, shell=True = Explorer bağlamı
    subprocess.Popen(
        str(p),
        cwd=str(p.parent),
        shell=True,
        creationflags=subprocess.DETACHED_PROCESS
    )
    return True


def _run_devtools_js(js_code, wait=0.8):
    """
    Aktif Vivaldi sekmesinde DevTools Console üzerinden JS çalıştırır.
    Sonuç copy() ile clipboard'a yazılır, string olarak döner.
    """
    if DRY_RUN:
        log.info(f'[DRY] DevTools JS çalıştırıldı')
        return 'dry_run'

    pyperclip.copy(js_code)
    pyautogui.hotkey('ctrl', 'shift', 'j')   # DevTools Console aç
    time.sleep(2.5)                          # DevTools tamamen açılsın

    # Vivaldi penceresinin altına göreceli tıkla → Console input focus
    # DevTools genellikle pencerenin alt ~30px'inde konumlanır
    wins = gw.getWindowsWithTitle('Vivaldi')
    if wins:
        win = wins[0]
        # Console ">" input alanı: sol taraftan 200px, pencerenin en altından 22px yukarıda
        cx = win.left + 200
        cy = win.bottom - 22
        pyautogui.click(cx, cy)
        log.info(f'DevTools Console input tıklandı: ({cx}, {cy})')
    time.sleep(0.5)

    pyautogui.hotkey('ctrl', 'v')            # JS kodunu yapıştır
    time.sleep(0.3)
    pyautogui.press('enter')                 # Çalıştır
    time.sleep(wait)
    pyautogui.hotkey('ctrl', 'shift', 'j')   # DevTools kapat
    time.sleep(0.5)

    result = pyperclip.paste().strip()
    # Clipboard hala JS kodunu içeriyorsa DevTools çalışmadı demektir
    if result == js_code.strip():
        log.warning('DevTools JS çalışmadı (clipboard değişmedi), hata döndürülüyor')
        return 'devtools_error'
    return result


def navigate_to_ceptel():
    """
    Vivaldi adres çubuğu (Ctrl+L) ile Google Messages sayfasına gider.
    Sayfa yüklenemezse 3 kez dener.
    """
    MESSAGES_URL = 'https://messages.google.com/web/conversations'

    log.info(f'Google Messages sayfasına gidiliyor: {MESSAGES_URL}')
    if DRY_RUN:
        log.info('[DRY] CepTel_Mesajlar açıldı')
        return

    for attempt in range(3):
        bring_to_front('Vivaldi')
        time.sleep(0.5)
        pyautogui.hotkey('ctrl', 'l')        # Adres çubuğuna odaklan
        time.sleep(0.8)
        pyautogui.hotkey('ctrl', 'a')        # Mevcut URL'yi seç
        pyautogui.typewrite(MESSAGES_URL, interval=0.03)
        time.sleep(0.3)
        pyautogui.press('enter')
        log.info(f'Sayfa yükleniyor (10 saniye)... (deneme {attempt+1}/3)')
        time.sleep(10)

        wins = gw.getWindowsWithTitle('Vivaldi')
        if wins:
            title = wins[0].title
            log.info(f'Vivaldi sekme başlığı: {title}')
            if 'mesaj' in title.lower() or 'message' in title.lower():
                log.info('Google Messages başarıyla yüklendi.')
                return
            log.warning(f'Sayfa yüklenmedi, tekrar deneniyor...')

    log.error('Google Messages 3 denemede de yüklenemedi, devam ediliyor...')


def dismiss_banner():
    """
    Google Messages 'Mobil veri kullanılıyor' gibi banner'ları kapatır.
    Önce Escape dener, sonra JS ile banner içindeki close butonunu tıklar.
    """
    log.info('Banner kontrol ediliyor...')
    if DRY_RUN:
        log.info('[DRY] Banner kapatma atlandı')
        return
    # Escape ile dene (bazı banner'ları kapatır)
    pyautogui.press('escape')
    time.sleep(0.5)
    # JS ile banner'ı bul ve kapat
    result = _run_devtools_js(_JS_DISMISS_BANNER, wait=0.8)
    if result == 'no_banner':
        log.info('Banner bulunamadı, devam ediliyor')
    else:
        log.info(f'Banner kapatıldı: {result}')
        time.sleep(1.0)


def search_infoyatirim(win):
    """
    Google Messages arama kutusu ile INFOYATIRIM konuşmasını bulup tıklar.
    Birkaç farklı arama simgesi konumu dener.
    """
    log.info('Google Messages arama ile INFOYATIRIM aranıyor...')

    # Sol panel ortasına önce tıkla — sayfa odağını al
    pyautogui.click(win.left + 180, win.top + 300)
    time.sleep(0.5)

    # Arama simgesini bul — sol panelin başlık alanında farklı x'ler dene
    # Google Messages: başlık yüksekliği ~64px, arama simgesi sağda
    opened = False
    for search_offset_x in [310, 330, 290, 350]:
        search_x = win.left + search_offset_x
        search_y = win.top + 65
        pyautogui.click(search_x, search_y)
        log.info(f'Arama simgesi deneniyor: ({search_x}, {search_y})')
        time.sleep(2.0)
        # Arama kutusu açıldıysa sayfanın bir şeyleri değişmiştir;
        # kontrol için: odak kaybetmeden hemen yaz ve bak
        pyperclip.copy('')
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.2)
        pyautogui.write('INFOYATIRIM', interval=0.06)
        time.sleep(0.5)
        # Eğer yazdığımız metin clipboard'a gidebiliyorsa
        # ya da en azından klavye odağı bir yerdeyse devam et
        opened = True
        break

    if not opened:
        log.warning('Arama simgesi açılamadı')
        return

    log.info('Arama metni yazıldı: INFOYATIRIM')
    time.sleep(3.0)   # Sonuçlar yüklensin

    # Sonuç listesinin ilk öğesini tıkla — arama açıkken başlık kayar,
    # ilk sonuç yaklaşık win.top + 120-140 arasında olur
    for result_y_offset in [130, 150, 110, 170]:
        result_x = win.left + 180
        result_y = win.top + result_y_offset
        pyautogui.click(result_x, result_y)
        log.info(f'Arama sonucu tıklandı: ({result_x}, {result_y})')
        time.sleep(3.5)
        # Vivaldi başlığı değiştiyse konuşma açıldı
        wins2 = gw.getWindowsWithTitle('Vivaldi')
        if wins2 and 'INFOYATIRIM' in wins2[0].title.upper():
            log.info('INFOYATIRIM konuşması açıldı (başlık doğrulandı)')
            return
        # İlk tıklamada konuşma açılmış olabilir bile başlık değişmeyebilir
        # — tek deneme yeterli, döngüden çık
        break


def click_infoyatirim():
    """
    Google Messages sol panelinde INFOYATIRIM konuşmasını bulup tıklar.
    Yöntem 1 (birincil): DevTools JS ile DOM'da 'INFOYATIRIM' metnini arar.
    Yöntem 2 (yedek):    locateOnScreen ile görsel template eşleştirme.
    Yöntem 3 (yedek):    Google Messages arama kutusunu kullanır.
    Yöntem 4 (son çare): Pencereye göre hesaplanmış koordinat.
    """
    log.info('INFOYATIRIM konuşması aranıyor...')
    if DRY_RUN:
        log.info('[DRY] INFOYATIRIM tıklandı')
        return

    wins = gw.getWindowsWithTitle('Vivaldi')
    if not wins:
        log.error('Vivaldi penceresi bulunamadı')
        sys.exit(1)
    win = wins[0]

    # Yöntem 1: DevTools JS
    result = _run_devtools_js(_JS_CLICK_INFOYATIRIM, wait=1.0)
    if result.startswith('ok'):
        log.info(f'INFOYATIRIM JS ile bulundu ve tıklandı: {result}')
        time.sleep(4)
        return

    log.warning(f'JS yöntemi başarısız ({result}), template aramaya geçiliyor...')

    # Yöntem 2: locateOnScreen — infoyatirim_template.png ile piksel eşleştirme
    template = SCRIPT_DIR / 'infoyatirim_template.png'
    if template.exists():
        try:
            import cv2  # noqa
            center = pyautogui.locateCenterOnScreen(str(template), confidence=0.75)
            if center:
                pyautogui.click(center)
                log.info(f'INFOYATIRIM template ile bulundu: {center}')
                time.sleep(4)
                return
            log.warning('Template eşleşmedi, arama yöntemine geçiliyor...')
        except Exception as e:
            log.warning(f'locateOnScreen başarısız: {e}')
    else:
        log.warning('infoyatirim_template.png bulunamadı')

    # Yöntem 3: Google Messages arama kutusu
    search_infoyatirim(win)
    log.info('Konuşma yükleniyor (arama yöntemi)...')
    return

    # Yöntem 4: Hesaplanmış koordinat (son çare — yukarıdaki return'den ulaşılamaz)
    # win.top + 238: "Sohbet başlatın" butonu dahil browser chrome hesabı
    cx = win.left + 180
    cy = win.top + 238
    pyautogui.click(cx, cy)
    log.info(f'INFOYATIRIM koordinat ile tıklandı: ({cx}, {cy})')
    time.sleep(4)


def extract_b001():
    """
    INFOYATIRIM konuşması açıkken Ctrl+A + Ctrl+C ile tüm sayfa
    metnini kopyalar, regex ile son B001 ibaresinin solundaki
    6 haneli sayıyı çeker.
    """
    import re as _re
    log.info('Son B001 verisi çekiliyor...')
    if DRY_RUN:
        return '123456'

    wins = gw.getWindowsWithTitle('Vivaldi')
    if not wins:
        log.error('Vivaldi penceresi bulunamadı')
        sys.exit(1)
    win = wins[0]

    # Mesaj içerik alanına tıkla (sol panel ~360px, geri kalan mesajlar)
    msg_x = win.left + 700
    msg_y = win.top + 400
    pyautogui.click(msg_x, msg_y)
    time.sleep(0.5)

    # En alta in (son mesajlar görünsün)
    pyautogui.hotkey('ctrl', 'end')
    time.sleep(1.0)

    # Tüm metni seç ve kopyala
    pyperclip.copy('')
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.3)
    pyautogui.hotkey('ctrl', 'c')
    time.sleep(0.8)

    text = pyperclip.paste()
    if not text:
        log.error('Sayfa metni kopyalanamadı')
        sys.exit(1)

    matches = _re.findall(r'(\d{6})\s*B001', text)
    if not matches:
        log.error('B001 kodu bulunamadı')
        sys.exit(1)

    value = matches[-1]
    log.info(f'B001 değeri: {value} ({len(matches)} eşleşmeden sonuncusu)')
    return value


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ANA OTOMASYON
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_skip_today():
    """
    Bugün hafta sonu veya Türkiye resmi/dini tatili ise True döner.
    Tatil tespitinde holidays kütüphanesi kullanılır
    (Ramazan Bayramı, Kurban Bayramı dahil tüm tatiller).
    """
    import holidays as _holidays
    from datetime import date as _date
    today = _date.today()
    if today.weekday() >= 5:   # 5=Cumartesi, 6=Pazar
        log.info(f'Bugün hafta sonu ({today.strftime("%A")}), otomasyon atlandı.')
        return True
    tr = _holidays.Turkey(years=today.year)
    if today in tr:
        log.info(f'Bugün resmi/dini tatil: {tr[today]} ({today}), otomasyon atlandı.')
        return True
    return False


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


def run():
    log.info('══════════════════════════════════════════')
    log.info('  SABAH OTOMASYONU BAŞLIYOR')
    log.info('══════════════════════════════════════════')

    if not FORCE_NOW and check_skip_today():
        return

    # ── Adım 1: MatriksIQ'yu başlat ────────────────────────
    open_shortcut(Path('C:/MatriksIQ/MatriksIQ.exe'))

    # ── Adım 2: Pencere görünene kadar bekle ────────────────
    wait_for_window('MatriksIQ')

    # ── Adım 3: Uygulama hazırlık süresi ────────────────────
    log.info('Uygulama hazırlık bekleniyor (45 saniye)...')
    time.sleep(45)

    # ── Adım 4: MatriksIQ ilk tıklamalar ───────────────────
    # PC açılışında mouse sol üst köşede kalabilir → fail-safe tetiklenir
    # İlk tıklamadan önce mouse'u güvenli bir konuma taşı
    pyautogui.moveTo(960, 540, duration=0.3)
    time.sleep(0.5)
    click(644,  42,  wait=2.0)
    click(2581, 701, wait=2.0)

    # Config'den şifreyi oku ve gir
    _cfg = configparser.ConfigParser()
    _cfg.read(SCRIPT_DIR / 'morning_config.ini', encoding='utf-8')
    _pwd = _cfg.get('matriksiq', 'password', fallback='')
    if not _pwd:
        log.error('morning_config.ini içinde [matriksiq] password bulunamadı. Çıkılıyor.')
        sys.exit(1)
    pyperclip.copy(_pwd)
    hotkey('ctrl', 'a')         # mevcut metni temizle
    hotkey('ctrl', 'v')         # şifreyi yapıştır
    time.sleep(0.2)
    press('enter',  wait=2.0)
    log.info('Şifre girildi ve Enter basıldı')

    click(2556, 808, wait=3)

    # ── Adım 5: Vivaldi'yi aç (zorunlu) ────────────────────
    vivaldi_path = DESKTOP / 'Vivaldi.lnk'
    open_shortcut(vivaldi_path, required=True)
    time.sleep(3)
    wait_for_window('Vivaldi')
    time.sleep(1)

    # ── Adım 6: CepTel_Mesajlar sayfasına git ──────────────
    # Koordinata bağlı değil — F2 Quick Commands ile açılır
    navigate_to_ceptel()

    # ── Adım 6.5: Banner'ı kapat (varsa) ───────────────────
    # "Mobil veri kullanılıyor" gibi banner'lar INFOYATIRIM'ı aşağı iter
    dismiss_banner()

    # ── Adım 7: INFOYATIRIM konuşmasını bul ve tıkla ───────
    # Koordinata bağlı değil — DevTools JS ile bulunur
    click_infoyatirim()

    # ── Adım 8: Son B001 verisini çek ──────────────────────
    # Koordinata bağlı değil — DevTools JS ile çekilir
    b001_value = extract_b001()

    # ── Adım 9: MatriksIQ'ya dön ve değeri yapıştır ────────
    bring_to_front('MatriksIQ')
    click(2557, 673)
    time.sleep(0.3)
    if not DRY_RUN:
        pyperclip.copy(b001_value)
    hotkey('ctrl', 'v')
    press('enter')
    log.info(f'B001 değeri yapıştırıldı: {b001_value}, Enter basıldı')
    # Enter sonrası 2s bekle — MatriksIQ ilgili pencereyi öne getirir
    time.sleep(2)
    click(3221, 255, wait=1)

    # ── Adım 10: Vivaldi'yi kapat ────────────────────────────
    close_vivaldi()

    # ── Adım 11: Kalan MatriksIQ tıklamaları ─────────────────
    bring_to_front('MatriksIQ')
    click(171,  323, wait=1)
    click(2725, 903, wait=5)

    # ── Adım 12: Uyarı/Bilgi dialog döngüsü ─────────────────
    # Uyarı (bot sayısı kadar) → 'Eski Versiyon İle Devam Et'
    # Bilgi (en son)           → 'Tamam'
    handle_dialogs()

    # ── Adım 13: Son tıklama ─────────────────────────────────
    click(2026, 878)

    # ── Adım 14: Explorer otomasyonu ─────────────────────────
    explorer_script = SCRIPT_DIR / 'explorer_start.pyw'
    if explorer_script.exists():
        log.info('Adım 14: Explorer otomasyonu başlatılıyor...')
        result = subprocess.run(
            [sys.executable, str(explorer_script)],
            cwd=str(SCRIPT_DIR),
        )
        if result.returncode == 0:
            log.info('Explorer otomasyonu başarıyla tamamlandı.')
        else:
            log.warning(f'Explorer otomasyonu hata kodu ile bitti: {result.returncode}')
    else:
        log.warning(f'Explorer script bulunamadı: {explorer_script}')

    log.info('══════════════════════════════════════════')
    log.info('  SABAH OTOMASYONU TAMAMLANDI')
    log.info('══════════════════════════════════════════')
    _send_notify('☀️ Sabah Otomasyonu Tamamlandı', 'MatriksIQ botları başarıyla başlatıldı.', 'morning-done')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BAŞLANGIÇ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MatriksIQ Sabah Otomasyonu')
    parser.add_argument('--test', action='store_true',
                        help='Adımları logla, mouse hareketi yapma')
    parser.add_argument('--now', action='store_true',
                        help='Hafta sonu/tatil kontrolünü atla (test için)')
    args = parser.parse_args()

    global FORCE_NOW
    if args.test:
        DRY_RUN = True
        log.info('TEST MODU — Mouse hareketi yok')
    if args.now:
        FORCE_NOW = True
        log.info('--now: Hafta sonu/tatil kontrolü atlanıyor')

    try:
        run()
    except KeyboardInterrupt:
        log.info('Kullanıcı tarafından durduruldu (Ctrl+C)')
    except TimeoutError as e:
        log.error(f'Zaman aşımı: {e}')
        sys.exit(1)
    except Exception as e:
        log.exception(f'Beklenmeyen hata: {e}')
        sys.exit(1)
