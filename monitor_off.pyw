#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor_off.pyw
Samsung LS49AG95 fiziksel monitörünü sabah otomasyonundan önce kapat.
09:11'de çalışır, iş günleri + arife günleri (hafta sonu/tatilde atlar).

Birincil yöntem : SetDisplayConfig  — Samsung'u Windows aktif ekran listesinden çıkarır.
                  Bu sayede AnyDesk fare/klavye olayları monitörü uyandıramaz.
İkincil yöntem  : DDC/CI            — Ekrana fiziksel güç kapatma sinyali gönderir.

Geri açma      : --restore          — Samsung'u extend modunda yeniden aktif eder.
                  Zamanlanmış görev  MatriksIQ_Monitor_Ac  16:55'te otomatik açar.
                  Masaüstü kısayolu  "Monitörü Geri Aç.lnk" ile elle açılabilir.

Kullanım:
  pythonw monitor_off.pyw            # Ekranı kapat (09:11 göreviyle)
  python  monitor_off.pyw --restore  # Samsung'u geri aç (extend modu)
  python  monitor_off.pyw --setup    # İki Task Scheduler görevi + masaüstü kısayolu
  python  monitor_off.pyw --test     # Hafta sonu/tatil atlamasız, direkt kapat
"""

import sys, time, logging, subprocess, argparse, ctypes, gc
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

TASK_NAME_OFF     = 'MatriksIQ_Monitor_Kapat'
TASK_NAME_RESTORE = 'MatriksIQ_Monitor_Ac'
TASK_TIME_OFF     = '09:11'
TASK_TIME_RESTORE = '16:55'          # Eve dönme öncesi Samsung'u geri aç
SCRIPT_DIR        = Path(__file__).parent
TARGET_MODEL      = 'LS49AG95'       # Hedef monitör (kısmi eşleşme, case-insensitive)
STARTUP_DELAY_SEC = 20               # Sistem sürücüleri yüklensin


# ══════════════════════════════════════════════════════════════════════
#  BÖLÜM 1 — Tatil kontrolü
# ══════════════════════════════════════════════════════════════════════

def check_skip_today():
    """
    Bugün hafta sonu veya Türkiye resmi/dini tatili ise True döner.
    Arife günleri tatil sayılmaz — sabah otomasyonu arife günleri de çalışır.
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
#  BÖLÜM 2 — Windows SetDisplayConfig (BİRİNCİL yöntem)
# ══════════════════════════════════════════════════════════════════════
#
#  SetDisplayConfig ile Samsung ekranı Windows'un aktif listesinden çıkarıyoruz.
#  Artık Windows o ekrana hiç sinyal göndermez; AnyDesk fare/klavye olayları
#  DPMS wake tetikleyemez çünkü ekran Windows için "yok" sayılıyor.
#
#  Geri açmak: SetDisplayConfig(SDC_TOPOLOGY_EXTEND) ile tüm ekranları extend
#  modunda yeniden aktif et.  Bu --restore / 16:55 görevi ile yapılır.
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
        ('targetAvailable',  wt.BOOL),
        ('statusFlags',      wt.UINT),
    ]

class _PATH_INFO(Structure):
    _fields_ = [
        ('sourceInfo', _PATH_SOURCE_INFO),
        ('targetInfo', _PATH_TARGET_INFO),
        ('flags',      wt.UINT),
    ]

class _MODE_INFO(Structure):
    # infoType(4) + id(4) + adapterId(8) + union(max 48 = TARGET_MODE)  → 64 byte
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
_QDC_ONLY_ACTIVE_PATHS             = 0x00000002
_SDC_USE_SUPPLIED_DISPLAY_CONFIG   = 0x00000020
_SDC_APPLY                         = 0x00000080
_SDC_NO_OPTIMIZATION               = 0x00000100
_SDC_SAVE_TO_DATABASE              = 0x00000200
_SDC_ALLOW_CHANGES                 = 0x00000400
_SDC_TOPOLOGY_EXTEND               = 0x00000004
_DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME = 2
_ERROR_SUCCESS                     = 0


def _win_disable_samsung() -> bool:
    """
    SetDisplayConfig ile Samsung LS49AG95 ekranını Windows aktif listesinden çıkar.
    Başarılıysa True, herhangi bir hata/eşleşme yoksa False döner.
    """
    user32 = ctypes.windll.user32

    # Tampon boyutlarını al
    num_paths = wt.UINT(0)
    num_modes = wt.UINT(0)
    ret = user32.GetDisplayConfigBufferSizes(
        _QDC_ONLY_ACTIVE_PATHS, byref(num_paths), byref(num_modes)
    )
    if ret != _ERROR_SUCCESS:
        log.error(f'GetDisplayConfigBufferSizes hata: {ret}')
        return False

    paths = (_PATH_INFO  * num_paths.value)()
    modes = (_MODE_INFO  * num_modes.value)()

    ret = user32.QueryDisplayConfig(
        _QDC_ONLY_ACTIVE_PATHS,
        byref(num_paths), paths,
        byref(num_modes), modes,
        None,
    )
    if ret != _ERROR_SUCCESS:
        log.error(f'QueryDisplayConfig hata: {ret}')
        return False

    n = num_paths.value
    log.info(f'Aktif ekran yolu: {n} adet')

    # Samsung yolunu bul
    samsung_idx = -1
    for i in range(n):
        p  = paths[i]
        ni = _TARGET_DEVICE_NAME()
        ni.header.type                  = _DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME
        ni.header.size                  = sizeof(_TARGET_DEVICE_NAME)
        ni.header.adapterId.LowPart     = p.targetInfo.adapterId.LowPart
        ni.header.adapterId.HighPart    = p.targetInfo.adapterId.HighPart
        ni.header.id                    = p.targetInfo.id
        r2 = user32.DisplayConfigGetDeviceInfo(byref(ni))
        fname = ni.monitorFriendlyDeviceName if r2 == _ERROR_SUCCESS else ''
        dpath = ni.monitorDevicePath         if r2 == _ERROR_SUCCESS else ''
        log.info(f'Ekran {i}: isim={fname!r}')
        if (TARGET_MODEL.lower() in fname.lower()
                or TARGET_MODEL.lower() in dpath.lower()):
            samsung_idx = i
            log.info(f'  → Hedef ({TARGET_MODEL}) eşleşti, yol indeksi: {i}')
            break

    if samsung_idx == -1:
        log.warning(f'{TARGET_MODEL} isimle eslesme bulunamadi — SetDisplayConfig atlandi.')
        return False

    # Samsung olmadan yeni yol dizisi oluştur
    new_paths_list = [paths[i] for i in range(n) if i != samsung_idx]
    new_count      = len(new_paths_list)

    if new_count == 0:
        # Samsung tek aktif ekran — SetDisplayConfig boş yol listesini reddeder (hata 87).
        # Bu durum genellikle sanal monitör o an inactive olduğunda yaşanır (ör. gece testi).
        # 09:11'de PC açılırken sanal monitör aktifse bu dal çalışmaz; o zaman new_count≥1 olur.
        log.warning(
            'Samsung tek aktif ekran — SetDisplayConfig uygulanamaz. '
            'Sanal monitörün o an aktif olduğundan emin olun. '
            'DDC/CI ile devam ediliyor.'
        )
        return False
    else:
        new_paths = (_PATH_INFO * new_count)(*new_paths_list)
        flags = (_SDC_USE_SUPPLIED_DISPLAY_CONFIG | _SDC_APPLY |
                 _SDC_ALLOW_CHANGES | _SDC_SAVE_TO_DATABASE)
        ret = user32.SetDisplayConfig(
            new_count, new_paths,
            num_modes.value, modes,
            flags,
        )
    if ret == _ERROR_SUCCESS:
        log.info('SetDisplayConfig ✓ — Samsung aktif listeden çıkarıldı (AnyDesk uyandıramaz).')
        return True
    else:
        log.warning(f'SetDisplayConfig başarısız: {ret}')
        return False


def _win_restore_displays() -> bool:
    """
    SetDisplayConfig SDC_TOPOLOGY_EXTEND ile tüm ekranları yeniden aktif et.
    Veritabanındaki ayarları kullanır; Samsung dahil tüm monitörler extend modunda açılır.
    """
    user32 = ctypes.windll.user32
    ret = user32.SetDisplayConfig(
        0, None, 0, None,
        _SDC_APPLY | _SDC_TOPOLOGY_EXTEND,
    )
    if ret == _ERROR_SUCCESS:
        log.info('SetDisplayConfig restore ✓ — tüm ekranlar extend modunda geri açıldı.')
        return True
    else:
        log.warning(f'SetDisplayConfig restore başarısız: {ret}')
        return False


# ══════════════════════════════════════════════════════════════════════
#  BÖLÜM 3 — DDC/CI (İKİNCİL yöntem — ekrana güç kapatma sinyali)
# ══════════════════════════════════════════════════════════════════════

def _ddc_turn_off() -> bool:
    """
    monitorcontrol ile fiziksel ekrana DDC/CI güç kapatma komutu gönder.
    Sanal monitörler DDC/CI desteklemez; sadece donanım ekranlar etkilenir.
    SetDisplayConfig başarılı olduktan sonra çağrılır (ekstra güvence).
    """
    from monitorcontrol import get_monitors, PowerMode

    modes_to_try = [
        ('off_soft',  PowerMode.off_soft),
        ('off_hard',  PowerMode.off_hard),
        ('standby',   PowerMode.standby),
        ('suspend',   PowerMode.suspend),
    ]

    monitors = list(get_monitors())
    log.info(f'DDC/CI monitör sayısı: {len(monitors)}')
    if not monitors:
        log.info('DDC/CI monitör bulunamadı (sanal monitörde normal).')
        return False

    for i, monitor in enumerate(monitors):
        try:
            with monitor:
                try:
                    caps  = monitor.get_vcp_capabilities()
                    model = caps.get('model', '') if isinstance(caps, dict) else ''
                except Exception:
                    model = ''
                desc = getattr(monitor.vcp, 'description', '') or ''
                log.info(f'DDC monitör {i}: model={model!r}, desc={desc!r}')

                t = TARGET_MODEL.lower()
                if not (t in model.lower() or t in desc.lower() or not model.strip()):
                    log.info(f'DDC monitör {i}: hedef değil, atlandı.')
                    continue

                # DDC hattını ısıt
                try:
                    monitor.get_luminance()
                except Exception:
                    pass
                time.sleep(0.1)

                for name, mode in modes_to_try:
                    try:
                        monitor.set_power_mode(mode)
                        log.info(f'DDC/CI ✓ — güç modu: {name}')
                        return True
                    except Exception as e:
                        log.debug(f'DDC/CI {name}: {e}')
        except Exception as e:
            log.warning(f'DDC monitör {i} hatası: {e}')

    log.info('DDC/CI ile güç modu ayarlanamadı.')
    return False


# ══════════════════════════════════════════════════════════════════════
#  BÖLÜM 4 — Task Scheduler + masaüstü kısayolu kurulumu
# ══════════════════════════════════════════════════════════════════════

def _create_task(name: str, time_str: str, extra_args: str = '') -> bool:
    python = str(Path(sys.executable).parent / 'pythonw.exe')
    script = str(SCRIPT_DIR / 'monitor_off.pyw')
    tr_arg = f' {extra_args}' if extra_args else ''

    subprocess.run(
        f'schtasks /Delete /TN "{name}" /F',
        shell=True, capture_output=True,
    )
    cmd = (
        f'schtasks /Create /TN "{name}" '
        f'/TR "\\"{python}\\" \\"{script}\\"{tr_arg}" '
        f'/SC WEEKLY /D MON,TUE,WED,THU,FRI '
        f'/ST {time_str} /F'
    )
    r = subprocess.run(cmd, shell=True, capture_output=True,
                       text=True, encoding='utf-8', errors='replace')
    ok = r.returncode == 0
    status = 'OK' if ok else 'HATA'
    print(f'  [{status}] Gorev: "{name}" @ {time_str} (Pzt-Cum){tr_arg}')
    if not ok:
        print(f'       Hata: {(r.stdout + r.stderr).strip()}')
    return ok


def _create_desktop_shortcut():
    """Masaüstünde 'Monitörü Geri Aç' kısayolu oluştur (VBScript ile)."""
    python = str(Path(sys.executable).parent / 'pythonw.exe')
    script = str(SCRIPT_DIR / 'monitor_off.pyw')
    desktop = Path.home() / 'Desktop'
    lnk_path = desktop / 'Monitor Geri Ac.lnk'

    lines = [
        'Set oShell = CreateObject("WScript.Shell")',
        'Set oLink  = oShell.CreateShortcut("' + str(lnk_path) + '")',
        'oLink.TargetPath       = "' + python + '"',
        'oLink.Arguments        = chr(34) & "' + script + '" & chr(34) & " --restore"',
        'oLink.WorkingDirectory = "' + str(SCRIPT_DIR) + '"',
        'oLink.Description      = "Samsung LS49AG95 monitoru geri ac (extend modu)"',
        'oLink.Save',
    ]
    vbs = '\n'.join(lines)

    vbs_file = SCRIPT_DIR / '_mk_shortcut.vbs'
    vbs_file.write_text(vbs, encoding='utf-8')
    r = subprocess.run(['cscript', '//nologo', str(vbs_file)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    vbs_file.unlink(missing_ok=True)

    ok = lnk_path.exists()
    print(f'  [{"OK" if ok else "HATA"}] Masaustu kisayolu: {lnk_path}')
    return ok


def setup_task():
    print('Task Scheduler görevleri oluşturuluyor…')
    _create_task(TASK_NAME_OFF,     TASK_TIME_OFF)
    _create_task(TASK_NAME_RESTORE, TASK_TIME_RESTORE, '--restore')
    print()
    print('Masaüstü kısayolu oluşturuluyor…')
    _create_desktop_shortcut()
    print()
    print('Kurulum tamamlandi.')
    print()
    print(f'  {TASK_TIME_OFF}   -> Samsung devre disi (AnyDesk uyandıramaz)')
    print(f'  {TASK_TIME_RESTORE}   -> Samsung otomatik geri acilir (extend)')
    print( '  Eve erken gelirseniz: "Monitoru Geri Ac" kisayoluna tiklayin')
    print( '                    ya da Win+P -> Genislet yapın')


# ══════════════════════════════════════════════════════════════════════
#  BÖLÜM 5 — Ana akışlar
# ══════════════════════════════════════════════════════════════════════

def run(skip_check=False):
    log.info('══════════════════════════════════════════')
    log.info('  MONİTÖR KAPATMA BAŞLIYOR')
    log.info('══════════════════════════════════════════')

    if not skip_check and check_skip_today():
        return

    if skip_check:
        log.info('--test modu: sistem gecikmesi atlandı.')
    else:
        log.info(f'Sistem hazırlık gecikmesi: {STARTUP_DELAY_SEC}s…')
        time.sleep(STARTUP_DELAY_SEC)

    # 1) SetDisplayConfig — AnyDesk'i körleştir
    sdc_ok = _win_disable_samsung()
    if not sdc_ok:
        log.warning('SetDisplayConfig başarısız; DDC/CI tek yöntem olarak devam ediyor.')

    # 2) DDC/CI — ekrana güç kapatma sinyali (ek güvence)
    ddc_ok = _ddc_turn_off()

    if sdc_ok:
        log.info('Sonuç: SetDisplayConfig ✓ (AnyDesk uyandıramaz) + DDC/CI '
                 + ('✓' if ddc_ok else 'denemedi/başarısız'))
    elif ddc_ok:
        log.warning('Sonuç: Yalnızca DDC/CI ✓ — AnyDesk bağlanınca monitör yeniden '
                    'uyanabilir (SetDisplayConfig çalışmadı).')
    else:
        log.error('Sonuç: Her iki yöntem de başarısız.')

    log.info('Tamamlandı.')


def restore():
    log.info('══════════════════════════════════════════')
    log.info('  MONİTÖR GERİ AÇMA BAŞLIYOR')
    log.info('══════════════════════════════════════════')
    ok = _win_restore_displays()
    if not ok:
        log.error('Monitör geri açılamadı.')
    log.info('Tamamlandı.')


# ══════════════════════════════════════════════════════════════════════
#  GİRİŞ NOKTASI
# ══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Samsung LS49AG95 monitör kontrolü')
    parser.add_argument('--setup',   action='store_true',
                        help='Task Scheduler görevleri + masaüstü kısayolu oluştur')
    parser.add_argument('--restore', action='store_true',
                        help='Samsung monitörü extend modunda geri aç')
    parser.add_argument('--test',    action='store_true',
                        help='Tatil/hafta sonu kontrolünü atla, direkt kapat')
    args = parser.parse_args()

    if args.setup:
        setup_task()
    elif args.restore:
        restore()
    else:
        run(skip_check=args.test)
