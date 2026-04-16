#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor_off.pyw
Samsung LS49AG95 fiziksel monitörünü sabah otomasyonundan önce kapat ve izle.

─ Kapatma (09:11, iş günleri)
    SetDisplayConfig ile Samsung Windows aktif listesinden çıkarılır.
    AnyDesk fare/klavye olayları artık monitörü uyandıramaz.

─ Otomatik geri açma (arka plan watcher)
    Windows login'de otomatik başlar (Registry autostart).
    Kullanıcı fiziksel güç tuşuna basınca HPD algılanır (QDC_ALL_PATHS targetAvailable),
    SetDisplayConfig restore çağrılır — ekranda masaüstü belirir.
    Klavye kısayolu veya masaüstü kısayoluna gerek yok.

Kullanım:
  pythonw monitor_off.pyw            # Ekranı kapat (09:11 göreviyle çalışır)
  pythonw monitor_off.pyw --watch    # Watcher — arka planda HPD izle (login'de otomatik)
  python  monitor_off.pyw --restore  # Elle geri aç (extend modu)
  python  monitor_off.pyw --setup    # Task Scheduler + Registry autostart + kısayol
  python  monitor_off.pyw --test     # Tatil atlamasız, direkt kapat (test)
"""

import sys, time, logging, subprocess, argparse, ctypes
import ctypes.wintypes as wt
from ctypes import Structure, byref, sizeof, c_wchar
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

SCRIPT_DIR        = Path(__file__).parent
TARGET_MODEL      = 'LS49AG95'       # Hedef monitör (kısmi, case-insensitive)
STARTUP_DELAY_SEC = 20               # Boot sonrası sürücülerin yüklenmesi için

TASK_NAME_OFF     = 'MatriksIQ_Monitor_Kapat'
TASK_TIME_OFF     = '09:11'

# Disable öncesi tam display config buraya kaydedilir;
# restore sırasında orijinal pozisyon/çözünürlük korunur.
SAVED_CONFIG_FILE = SCRIPT_DIR / '.samsung_config.pkl'

# Watcher ayarları
DISABLED_FLAG          = SCRIPT_DIR / '.samsung_disabled'
POLL_INTERVAL_SEC      = 8           # Her N saniyede bir QDC_ALL_PATHS kontrol
WAIT_AFTER_DISABLE_SEC = 180         # Samsung "No Signal" sonrası kapanır; en az 3dk bekle


# ══════════════════════════════════════════════════════════════════════
#  BÖLÜM 1 — Tatil kontrolü
# ══════════════════════════════════════════════════════════════════════

def check_skip_today() -> bool:
    """
    Bugün hafta sonu veya Türkiye resmi/dini tatili ise True döner.
    Arife günleri tatil sayılmaz (sabah otomasyonu arife günleri de çalışır).
    """
    import holidays as _holidays
    today = date.today()
    if today.weekday() >= 5:
        log.info(f'Hafta sonu ({today.strftime("%A")}), atlandı.')
        return True
    tr = _holidays.Turkey(years=today.year)
    if today in tr:
        log.info(f'Resmi/dini tatil: {tr[today]} ({today}), atlandı.')
        return True
    return False


# ══════════════════════════════════════════════════════════════════════
#  BÖLÜM 2 — Windows SetDisplayConfig
# ══════════════════════════════════════════════════════════════════════
#
#  Kapatma  : Samsung'u Windows aktif ekran listesinden çıkar.
#             Windows artık o porta sinyal göndermez → AnyDesk uyandıramaz.
#  Geri açma: SDC_TOPOLOGY_EXTEND ile tüm ekranları extend modunda aç.
#  Algılama : QDC_ALL_PATHS + targetAvailable → Samsung fiziksel durumu.
# ──────────────────────────────────────────────────────────────────────

# ── ctypes yapıları ────────────────────────────────────────────────────

class _LUID(Structure):
    _fields_ = [('LowPart', wt.DWORD), ('HighPart', wt.LONG)]

class _RATIONAL(Structure):
    _fields_ = [('Numerator', wt.UINT), ('Denominator', wt.UINT)]

class _PATH_SOURCE_INFO(Structure):
    _fields_ = [
        ('adapterId',   _LUID),
        ('id',          wt.UINT),
        ('modeInfoIdx', wt.UINT),
        ('statusFlags', wt.UINT),
    ]

class _PATH_TARGET_INFO(Structure):
    _fields_ = [
        ('adapterId',        _LUID),
        ('id',               wt.UINT),
        ('modeInfoIdx',      wt.UINT),
        ('outputTechnology', wt.UINT),
        ('rotation',         wt.UINT),
        ('scaling',          wt.UINT),
        ('refreshRate',      _RATIONAL),
        ('scanLineOrdering', wt.UINT),
        ('targetAvailable',  wt.BOOL),   # Fiziksel varlık bayrağı
        ('statusFlags',      wt.UINT),
    ]

class _PATH_INFO(Structure):
    _fields_ = [
        ('sourceInfo', _PATH_SOURCE_INFO),
        ('targetInfo', _PATH_TARGET_INFO),
        ('flags',      wt.UINT),
    ]

class _MODE_INFO(Structure):
    # infoType(4) + id(4) + adapterId(8) + union(max 48=TARGET_MODE) = 64 byte
    _fields_ = [
        ('infoType',   wt.UINT),
        ('id',         wt.UINT),
        ('adapterId',  _LUID),
        ('modeData',   ctypes.c_uint8 * 48),
    ]

class _DEV_INFO_HEADER(Structure):
    _fields_ = [
        ('type',       wt.UINT),
        ('size',       wt.UINT),
        ('adapterId',  _LUID),
        ('id',         wt.UINT),
    ]

class _TARGET_DEVICE_NAME(Structure):
    _fields_ = [
        ('header',                    _DEV_INFO_HEADER),
        ('flags',                     wt.UINT),
        ('outputTechnology',          wt.UINT),
        ('edidManufactureId',         wt.USHORT),
        ('edidProductCodeId',         wt.USHORT),
        ('connectorInstance',         wt.UINT),
        ('monitorFriendlyDeviceName', c_wchar * 64),
        ('monitorDevicePath',         c_wchar * 128),
    ]

# Windows sabitleri
_QDC_ONLY_ACTIVE_PATHS           = 0x00000002
_QDC_ALL_PATHS                   = 0x00000001
_SDC_USE_SUPPLIED_DISPLAY_CONFIG = 0x00000020
_SDC_APPLY                       = 0x00000080
_SDC_SAVE_TO_DATABASE            = 0x00000200
_SDC_ALLOW_CHANGES               = 0x00000400
_SDC_TOPOLOGY_EXTEND             = 0x00000004
_DISPLAYCONFIG_INFO_GET_TARGET   = 2
_ERROR_SUCCESS                   = 0


def _find_samsung_in_paths(qdc_flags: int) -> tuple:
    """
    Verilen QDC flags ile QueryDisplayConfig çalıştır.
    Samsung bulunursa (adapterId, targetId, targetAvailable) tuple döner, yoksa None.
    QDC_ALL_PATHS ile targetAvailable=False olan yollar da dahildir.
    """
    user32 = ctypes.windll.user32
    np, nm = wt.UINT(0), wt.UINT(0)
    if user32.GetDisplayConfigBufferSizes(qdc_flags, byref(np), byref(nm)) != _ERROR_SUCCESS:
        return None
    paths = (_PATH_INFO * np.value)()
    modes = (_MODE_INFO * nm.value)()
    if user32.QueryDisplayConfig(qdc_flags, byref(np), paths, byref(nm), modes, None) != _ERROR_SUCCESS:
        return None

    for i in range(np.value):
        p = paths[i]
        ni = _TARGET_DEVICE_NAME()
        ni.header.type                = _DISPLAYCONFIG_INFO_GET_TARGET
        ni.header.size                = sizeof(_TARGET_DEVICE_NAME)
        ni.header.adapterId.LowPart   = p.targetInfo.adapterId.LowPart
        ni.header.adapterId.HighPart  = p.targetInfo.adapterId.HighPart
        ni.header.id                  = p.targetInfo.id
        r = user32.DisplayConfigGetDeviceInfo(byref(ni))
        fname = ni.monitorFriendlyDeviceName if r == _ERROR_SUCCESS else ''
        dpath = ni.monitorDevicePath         if r == _ERROR_SUCCESS else ''
        if (TARGET_MODEL.lower() in fname.lower()
                or TARGET_MODEL.lower() in dpath.lower()):
            return (
                (p.targetInfo.adapterId.LowPart, p.targetInfo.adapterId.HighPart),
                p.targetInfo.id,
                bool(p.targetInfo.targetAvailable),
                np.value,
                paths,
                nm.value,
                modes,
            )
    return None


def _samsung_is_physically_on() -> bool:
    """
    QDC_ALL_PATHS ile Samsung targetAvailable=True mi?
    True  → Samsung fiziksel olarak AÇIK (HPD hattı aktif).
    False → Samsung fiziksel olarak KAPALI veya bulunamadı.
    """
    result = _find_samsung_in_paths(_QDC_ALL_PATHS)
    if result is None:
        return False
    return result[2]  # targetAvailable


def _save_display_config() -> bool:
    """
    Mevcut aktif display config'i (paths + modes) dosyaya kaydet.
    Disable öncesi çağrılır; restore'da tam pozisyon/çözünürlük geri yüklenir.
    """
    import pickle
    user32 = ctypes.windll.user32
    np_v, nm_v = wt.UINT(0), wt.UINT(0)
    if user32.GetDisplayConfigBufferSizes(_QDC_ONLY_ACTIVE_PATHS, byref(np_v), byref(nm_v)) != _ERROR_SUCCESS:
        return False
    paths = (_PATH_INFO * np_v.value)()
    modes = (_MODE_INFO * nm_v.value)()
    if user32.QueryDisplayConfig(
        _QDC_ONLY_ACTIVE_PATHS, byref(np_v), paths, byref(nm_v), modes, None
    ) != _ERROR_SUCCESS:
        return False
    data = {'np': np_v.value, 'nm': nm_v.value,
            'paths': bytes(paths), 'modes': bytes(modes)}
    SAVED_CONFIG_FILE.write_bytes(pickle.dumps(data))
    log.info(f'Display config kaydedildi: {np_v.value} yol, {nm_v.value} mod.')
    return True


def _win_disable_samsung() -> bool:
    """
    Samsung'u Windows aktif ekran listesinden çıkar.
    Önce tam config kaydedilir (restore'da pozisyon korunur).
    SDC_SAVE_TO_DATABASE KULLANILMAZ — database bozulmasın.
    """
    user32 = ctypes.windll.user32
    result = _find_samsung_in_paths(_QDC_ONLY_ACTIVE_PATHS)

    if result is None:
        log.warning(f'{TARGET_MODEL} aktif yollarda bulunamadı — SetDisplayConfig atlandı.')
        return False

    adapter_id, target_id, _, n, paths, nm, modes = result
    log.info(f'Aktif ekran yolu: {n} adet — Samsung bulundu.')

    # Restore'da pozisyon korunsun diye disable ÖNCESİ kaydet
    _save_display_config()

    # Samsung olmadan yeni yol dizisi
    new_list = []
    for i in range(n):
        p = paths[i]
        if not (p.targetInfo.adapterId.LowPart == adapter_id[0]
                and p.targetInfo.adapterId.HighPart == adapter_id[1]
                and p.targetInfo.id == target_id):
            new_list.append(p)

    if not new_list:
        log.warning(
            'Samsung tek aktif ekran — SetDisplayConfig uygulanamaz. '
            'Sanal monitörün o an aktif olduğundan emin olun.'
        )
        return False

    new_paths = (_PATH_INFO * len(new_list))(*new_list)
    # SDC_USE_SUPPLIED_DISPLAY_CONFIG + tam modes array: çalışan yöntem.
    # Samsung'a ait mode girişleri artık hiçbir path'e referans verilmiyor;
    # SDC_ALLOW_CHANGES ile Windows bunları yok sayar.
    # Orijinal config disable ÖNCE kaydedildiğinden restore tam pozisyonla yapılır.
    flags = (_SDC_USE_SUPPLIED_DISPLAY_CONFIG | _SDC_APPLY | _SDC_ALLOW_CHANGES)
    ret = user32.SetDisplayConfig(len(new_list), new_paths, nm, modes, flags)
    if ret == _ERROR_SUCCESS:
        log.info('SetDisplayConfig disable OK — AnyDesk artik uyandıramaz.')
        return True
    log.warning(f'SetDisplayConfig disable basarisiz: {ret}')
    return False


def _set_vdd_resolution_1080p() -> None:
    """
    VDD (sanal monitör) çözünürlüğünü 1920x1080 yap.
    Restore sonrası çağrılır — duvar kağıdı uzamasını önler.
    """
    import struct
    user32 = ctypes.windll.user32
    np_v, nm_v = wt.UINT(0), wt.UINT(0)
    if user32.GetDisplayConfigBufferSizes(_QDC_ONLY_ACTIVE_PATHS, byref(np_v), byref(nm_v)) != _ERROR_SUCCESS:
        return
    paths = (_PATH_INFO * np_v.value)()
    modes = (_MODE_INFO * nm_v.value)()
    if user32.QueryDisplayConfig(
        _QDC_ONLY_ACTIVE_PATHS, byref(np_v), paths, byref(nm_v), modes, None
    ) != _ERROR_SUCCESS:
        return

    changed = False
    for i in range(nm_v.value):
        m = modes[i]
        if m.infoType != 1:   # SOURCE mode
            continue
        raw = bytes(m.modeData)
        w, h, pf, px, py = struct.unpack_from('<IIIII', raw, 0)
        # Samsung degil (px!=0 veya w!=5120) ve cok yuksek cozunurluk = VDD
        if w == 5120 and h == 1440 and px != 0:
            new_raw = struct.pack('<IIIII', 1920, 1080, pf, px, py) + raw[20:]
            for j, b in enumerate(new_raw):
                m.modeData[j] = b
            changed = True
            log.info(f'VDD mode[{i}]: {w}x{h}->(1920x1080) pos=({px},{py})')

    if changed:
        flags = _SDC_USE_SUPPLIED_DISPLAY_CONFIG | _SDC_APPLY | _SDC_ALLOW_CHANGES
        ret = user32.SetDisplayConfig(np_v.value, paths, nm_v.value, modes, flags)
        if ret == _ERROR_SUCCESS:
            log.info('VDD 1920x1080 ayarlandi.')
        else:
            log.warning(f'VDD cozunurluk degisimi basarisiz: {ret}')


def _win_restore_displays() -> bool:
    """
    Kaydedilen tam config ile restore et (orijinal pozisyon korunur).
    Kayıt yoksa SDC_TOPOLOGY_EXTEND fallback.
    Restore sonrası VDD otomatik 1920x1080 yapılır (duvar kağıdı uzamasın).
    """
    import pickle
    user32 = ctypes.windll.user32

    if SAVED_CONFIG_FILE.exists():
        try:
            data  = pickle.loads(SAVED_CONFIG_FILE.read_bytes())
            np_v  = data['np']
            nm_v  = data['nm']
            paths = (_PATH_INFO * np_v).from_buffer_copy(data['paths'])
            modes = (_MODE_INFO * nm_v).from_buffer_copy(data['modes'])
            flags = (_SDC_USE_SUPPLIED_DISPLAY_CONFIG | _SDC_APPLY | _SDC_ALLOW_CHANGES)
            ret = user32.SetDisplayConfig(np_v, paths, nm_v, modes, flags)
            if ret == _ERROR_SUCCESS:
                log.info('Kaydedilen display config restore edildi — pozisyon korundu.')
                SAVED_CONFIG_FILE.unlink(missing_ok=True)
                _set_vdd_resolution_1080p()
                return True
            log.warning(f'Kaydedilen config restore basarisiz ({ret}), fallback deneniyor.')
        except Exception as e:
            log.error(f'Config yukleme hatasi: {e}')

    # Fallback: SDC_TOPOLOGY_EXTEND (SAVE_TO_DATABASE olmadan — o flag error 87 verir)
    ret = user32.SetDisplayConfig(0, None, 0, None, _SDC_APPLY | _SDC_TOPOLOGY_EXTEND)
    if ret == _ERROR_SUCCESS:
        log.info('SetDisplayConfig extend restore OK (fallback).')
        SAVED_CONFIG_FILE.unlink(missing_ok=True)
        _set_vdd_resolution_1080p()
        return True
    log.warning(f'SetDisplayConfig restore basarisiz: {ret}')
    return False


def _fix_offscreen_windows() -> None:
    """
    Restore sonrası görünmez alanda kalan pencereleri birincil monitöre taşı.
    MonitorFromRect=NULL olanlar + x>=5000 olanlar (VDD'de kalanlar) taşınır.
    """
    user32 = ctypes.windll.user32
    MONITOR_DEFAULTTONULL = 0x00000000
    SWP_NOSIZE            = 0x0001
    SWP_NOZORDER          = 0x0004
    SWP_NOACTIVATE        = 0x0010
    moved = 0

    def _cb(hwnd, _):
        nonlocal moved
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            rect = wt.RECT()
            user32.GetWindowRect(hwnd, byref(rect))
            off_mon  = (user32.MonitorFromRect(byref(rect), MONITOR_DEFAULTTONULL) == 0)
            off_vdd  = (rect.left >= 5000)   # VDD'de kalan (Samsung 5120px genisliginde)
            if off_mon or off_vdd:
                w = max(rect.right  - rect.left, 1)
                h = max(rect.bottom - rect.top,  1)
                nx = max(50, min(4900 - w, 400))
                ny = max(50, min(1300 - h, 200))
                user32.SetWindowPos(
                    hwnd, 0, nx, ny, 0, 0,
                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
                )
                moved += 1
        except Exception:
            pass
        return True

    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    user32.EnumWindows(EnumProc(_cb), 0)
    if moved:
        log.info(f'{moved} pencere Samsung monitore tasindi.')


# ══════════════════════════════════════════════════════════════════════
#  BÖLÜM 3 — DDC/CI (ikincil yöntem)
# ══════════════════════════════════════════════════════════════════════

def _ddc_turn_off() -> bool:
    """DDC/CI ile fiziksel ekrana güç kapatma sinyali gönder (ikincil/ek)."""
    from monitorcontrol import get_monitors, PowerMode
    monitors = list(get_monitors())
    log.info(f'DDC/CI monitör sayısı: {len(monitors)}')
    if not monitors:
        return False
    for i, monitor in enumerate(monitors):
        try:
            with monitor:
                try:
                    caps  = monitor.get_vcp_capabilities()
                    model = caps.get('model', '') if isinstance(caps, dict) else ''
                except Exception:
                    model = ''
                t = TARGET_MODEL.lower()
                if model and t not in model.lower():
                    continue
                try:
                    monitor.get_luminance()
                except Exception:
                    pass
                time.sleep(0.1)
                for name, mode in [('off_soft', PowerMode.off_soft),
                                   ('off_hard', PowerMode.off_hard),
                                   ('standby',  PowerMode.standby)]:
                    try:
                        monitor.set_power_mode(mode)
                        log.info(f'DDC/CI ✓ — {name}')
                        return True
                    except Exception as e:
                        log.debug(f'DDC/CI {name}: {e}')
        except Exception as e:
            log.warning(f'DDC monitör {i}: {e}')
    log.info('DDC/CI güç modu ayarlanamadı.')
    return False


# ══════════════════════════════════════════════════════════════════════
#  BÖLÜM 4 — Watcher (arka plan — HPD otomatik algılama)
# ══════════════════════════════════════════════════════════════════════
#
#  Akış:
#    1. monitor_off.pyw Samsung'u disable eder + DISABLED_FLAG dosyası oluşturur.
#    2. Samsung "No Signal" gösterir, ~30-60 sn sonra fiziksel olarak kapanır.
#       _samsung_is_physically_on() → False  →  seen_off = True
#    3. Kullanıcı eve gelir, güç tuşuna basar.
#       Samsung açılır, HPD sinyali GPU'ya ulaşır.
#       _samsung_is_physically_on() → True  +  seen_off = True  →  RESTORE!
#    4. _win_restore_displays() çağrılır, Samsung masaüstünü gösterir.
#       DISABLED_FLAG silinir, watcher bekleme moduna döner.
# ──────────────────────────────────────────────────────────────────────

def watch_loop() -> None:
    """
    Samsung güç tuşunu izle; basıldığında otomatik restore et.
    Windows login'de otomatik başlatılır (Registry autostart, --setup ile eklenir).
    """
    log.info('Monitor watcher baslatildi.')
    seen_off = False          # Samsung'un fiziksel olarak kapandığını gördük mü?
    last_flag_mtime = 0.0

    while True:
        try:
            if not DISABLED_FLAG.exists():
                # Samsung kasıtlı kapatılmamış — bekle
                seen_off = False
                last_flag_mtime = 0.0
                time.sleep(POLL_INTERVAL_SEC)
                continue

            # Flag var: Samsung kasıtlı kapatıldı
            flag_mtime = DISABLED_FLAG.stat().st_mtime
            if flag_mtime != last_flag_mtime:
                seen_off = False   # Yeni bir disable işlemi — sıfırla
                last_flag_mtime = flag_mtime

            elapsed = time.time() - flag_mtime

            on = _samsung_is_physically_on()

            if not on:
                # Samsung fiziksel olarak kapandı — artık güç tuşuna basılmasını bekle
                if not seen_off:
                    log.info('Samsung fiziksel olarak kapandi; guc tusu bekleniyor...')
                seen_off = True
            else:
                # Samsung fiziksel olarak ACIK
                if seen_off or elapsed >= WAIT_AFTER_DISABLE_SEC:
                    # Kullanıcı güç tuşuna bastı (veya yeterli süre geçti) → restore
                    log.info(
                        f'Samsung guc tusuna basildi algilandi '
                        f'(seen_off={seen_off}, elapsed={elapsed:.0f}s) — restore...'
                    )
                    if _win_restore_displays():
                        DISABLED_FLAG.unlink(missing_ok=True)
                        seen_off = False
                        time.sleep(1)              # Sürücünün ekranı tanıması için
                        _fix_offscreen_windows()   # Kaymış pencereleri düzelt
                        log.info('Restore tamamlandi. Watcher bekleme moduna dondu.')
                        time.sleep(30)   # Restore sonrası kısa bekleme
                # else: Samsung henüz kapanmadı (No Signal aşaması), bekle

        except Exception as e:
            log.debug(f'Watch loop hatasi: {e}')

        time.sleep(POLL_INTERVAL_SEC)


# ══════════════════════════════════════════════════════════════════════
#  BÖLÜM 5 — Kurulum (Task Scheduler + Registry + kısayol)
# ══════════════════════════════════════════════════════════════════════

def _create_schtask(name: str, time_str: str, extra_args: str = '') -> bool:
    python = str(Path(sys.executable).parent / 'pythonw.exe')
    script = str(SCRIPT_DIR / 'monitor_off.pyw')
    tr_arg = f' {extra_args}' if extra_args else ''
    subprocess.run(f'schtasks /Delete /TN "{name}" /F',
                   shell=True, capture_output=True)
    cmd = (
        f'schtasks /Create /TN "{name}" '
        f'/TR "\\"{python}\\" \\"{script}\\"{tr_arg}" '
        f'/SC WEEKLY /D MON,TUE,WED,THU,FRI /ST {time_str} /F'
    )
    r = subprocess.run(cmd, shell=True, capture_output=True,
                       text=True, encoding='utf-8', errors='replace')
    ok = r.returncode == 0
    print(f'  [{"OK" if ok else "HATA"}] Gorev: "{name}" @ {time_str} (Pzt-Cum){tr_arg}')
    if not ok:
        print(f'       {(r.stdout + r.stderr).strip()}')
    return ok


def _setup_watcher_autostart() -> bool:
    """Watcher'ı Windows login'de otomatik başlat (Registry HKCU\\Run)."""
    import winreg
    python = str(Path(sys.executable).parent / 'pythonw.exe')
    script = str(SCRIPT_DIR / 'monitor_off.pyw')
    cmd    = f'"{python}" "{script}" --watch'
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Run',
            0, winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, 'MonitorWatch', 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        print('  [OK] Watcher Registry autostart eklendi (her login\'de baslar)')
        return True
    except Exception as e:
        print(f'  [HATA] Registry: {e}')
        return False


def _start_watcher_now() -> None:
    """Watcher'ı şimdi arka planda başlat (henüz çalışmıyorsa)."""
    python = str(Path(sys.executable).parent / 'pythonw.exe')
    script = str(SCRIPT_DIR / 'monitor_off.pyw')
    subprocess.Popen([python, script, '--watch'],
                     creationflags=0x00000008,   # DETACHED_PROCESS
                     close_fds=True)


def _create_desktop_shortcut() -> bool:
    """Masaüstünde 'Monitor Geri Ac' kısayolu oluştur (yedek el kısayolu)."""
    python   = str(Path(sys.executable).parent / 'pythonw.exe')
    script   = str(SCRIPT_DIR / 'monitor_off.pyw')
    lnk_path = Path.home() / 'Desktop' / 'Monitor Geri Ac.lnk'
    lines = [
        'Set oShell = CreateObject("WScript.Shell")',
        'Set oLink  = oShell.CreateShortcut("' + str(lnk_path) + '")',
        'oLink.TargetPath       = "' + python + '"',
        'oLink.Arguments        = chr(34) & "' + script + '" & chr(34) & " --restore"',
        'oLink.WorkingDirectory = "' + str(SCRIPT_DIR) + '"',
        'oLink.Description      = "Samsung LS49AG95 monitoru geri ac"',
        'oLink.Save',
    ]
    vbs_file = SCRIPT_DIR / '_mk_shortcut.vbs'
    vbs_file.write_text('\n'.join(lines), encoding='utf-8')
    subprocess.run(['cscript', '//nologo', str(vbs_file)],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')
    vbs_file.unlink(missing_ok=True)
    ok = lnk_path.exists()
    print(f'  [{"OK" if ok else "HATA"}] Masaustu kisayolu (yedek): {lnk_path}')
    return ok


def setup():
    """Task Scheduler + Registry watcher autostart + masaüstü kısayolu."""
    print('Task Scheduler gorevi olusturuluyor...')
    _create_schtask(TASK_NAME_OFF, TASK_TIME_OFF)

    # 16:55 restore görevi kaldırıldı — watcher otomatik hallediyor.
    # Eski görev varsa temizle.
    subprocess.run('schtasks /Delete /TN "MatriksIQ_Monitor_Ac" /F',
                   shell=True, capture_output=True)
    print('  [OK] Eski 16:55 restore gorevi kaldirildi (watcher gereksiz kildi).')

    print()
    print('Watcher Registry autostart ekleniyor...')
    _setup_watcher_autostart()

    print()
    print('Masaustu kisayolu olusturuluyor (yedek)...')
    _create_desktop_shortcut()

    print()
    print('Watcher simdi baslatiliyor...')
    _start_watcher_now()
    print('  [OK] Watcher arka planda calisiyor.')

    print()
    print('Kurulum tamamlandi.')
    print()
    print('  Calisma akisi:')
    print(f'  {TASK_TIME_OFF}  -> Samsung devre disi (AnyDesk uyandıramaz)')
    print( '  Gun ici  -> Watcher arka planda calisir')
    print( '  Eve gel  -> Guc tusuna bas, ~8sn icinde ekran acilir')
    print( '  (Yedek)  -> Masaustu "Monitor Geri Ac" kisayolu')


# ══════════════════════════════════════════════════════════════════════
#  BÖLÜM 6 — Ana akışlar
# ══════════════════════════════════════════════════════════════════════

def run(skip_check: bool = False) -> None:
    log.info('══════════════════════════════════════════')
    log.info('  MONITOR KAPATMA BASLIYOR')
    log.info('══════════════════════════════════════════')

    if not skip_check and check_skip_today():
        return

    if skip_check:
        log.info('--test modu: sistem gecikmesi atlandı.')
    else:
        log.info(f'Sistem hazırlık gecikmesi: {STARTUP_DELAY_SEC}s...')
        time.sleep(STARTUP_DELAY_SEC)

    # 1) SetDisplayConfig — birincil
    sdc_ok = _win_disable_samsung()

    # 2) Flag oluştur — watcher bunu izleyerek güç tuşunu algılar
    if sdc_ok:
        DISABLED_FLAG.touch()
        log.info('DISABLED_FLAG olusturuldu — watcher izlemeye basladi.')

    # 3) DDC/CI — ikincil (fiziksel güç kapatma sinyali)
    ddc_ok = _ddc_turn_off()

    if sdc_ok:
        log.info('Sonuc: SetDisplayConfig OK + DDC/CI ' + ('OK' if ddc_ok else 'basarisiz'))
    elif ddc_ok:
        log.warning('Sonuc: Yalniz DDC/CI OK — AnyDesk baglantisinda monitor uyanabilir.')
    else:
        log.error('Sonuc: Her iki yontem de basarisiz.')

    log.info('Tamamlandi.')


def restore() -> None:
    log.info('══════════════════════════════════════════')
    log.info('  MONITOR GERI ACMA BASLIYOR')
    log.info('══════════════════════════════════════════')
    ok = _win_restore_displays()
    if ok:
        DISABLED_FLAG.unlink(missing_ok=True)
        time.sleep(1)                   # Sürücünün ekranı tanıması için kısa bekle
        _fix_offscreen_windows()        # Görünmez alanda kalan pencereleri taşı
    else:
        log.error('Monitör geri açılamadı.')
    log.info('Tamamlandi.')


# ══════════════════════════════════════════════════════════════════════
#  GİRİŞ NOKTASI
# ══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Samsung LS49AG95 monitor kontrolu')
    parser.add_argument('--setup',   action='store_true',
                        help='Task Scheduler + Registry watcher + kisayol kur')
    parser.add_argument('--watch',   action='store_true',
                        help='Arka plan watcher — HPD izle, guc tusunda restore et')
    parser.add_argument('--restore', action='store_true',
                        help='Samsung monitoru extend modunda geri ac')
    parser.add_argument('--test',    action='store_true',
                        help='Tatil/hafta sonu kontrolunu atla, direkt kapat')
    args = parser.parse_args()

    if args.setup:
        setup()
    elif args.watch:
        watch_loop()
    elif args.restore:
        restore()
    else:
        run(skip_check=args.test)
