# -*- coding: utf-8 -*-
"""
health_watchdog.pyw — GridTracker Sistem Sağlık Bekçisi

Sürekli çalışır (Registry Run ile başlar). Görevleri:
  1. Tüm servisleri izler; düşeni GÖRÜNMEZ yeniden başlatır (60 sn'de bir).
  2. Piyasa açıkken DDE feed'ini canlı tutar (ensure_dde).
  3. Sabah ~09:30'da SADECE SORUN VARSA tek push bildirimi gönderir.
  4. Günde bir kez state.json + Firebase (scoreHistory/advisor) yedeği alır
     (küçük JSON dosyaları, son 14 gün; yer kaplamaz).

Kullanım:
  pythonw health_watchdog.pyw          # sürekli (servis)
  python  health_watchdog.pyw --once   # tek tur (test)
"""
import os
import sys
import json
import time
import shutil
import logging
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime, date, timedelta

for _pkg in ("psutil",):
    try:
        __import__(_pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", _pkg, "-q"])
import psutil

ROOT      = Path(__file__).parent
PYTHONW   = str(Path(sys.executable).with_name("pythonw.exe"))
BACKUPDIR = ROOT / "backups"
LOG_FILE  = ROOT / "health_watchdog.log"
FB_BASE   = "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app/gridtracker"

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

# İzlenen servisler: anahtar = cmdline'da aranan metin, değer = (script yolu, cwd)
SERVICES = {
    "server.py":                (ROOT / "server.py",                              ROOT),
    "automation_server.pyw":    (ROOT / "automation_server.pyw",                  ROOT),
    "grid_tracker_service.pyw": (ROOT / "grid_tracker_service.pyw",               ROOT),
    "Gunluk_Al_Sat\\monitor.pyw": (ROOT / "Gunluk_Al_Sat" / "monitor.pyw",        ROOT / "Gunluk_Al_Sat"),
    # Namaz vakti scripti (GridTracker dışında — mutlak yol). Sessizce düşerse
    # yarım gün ezan/uyarı gelmiyordu; artık watchdog ayakta tutuyor.
    "vakit_kontrol.py": (Path(r"C:\Users\BioCSI\Documents\Rainmeter\Skins\TestCountdown\vakit_kontrol.py"),
                         Path(r"C:\Users\BioCSI\Documents\Rainmeter\Skins\TestCountdown")),
}

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger("HealthWatchdog")

_last_restart = {}   # servis -> son restart zamanı (cooldown)


# ── NTFY ─────────────────────────────────────────────────────────────────────
def _ntfy_topic():
    try:
        cfg = json.loads((ROOT / "grid_analysis_config.json").read_text(encoding="utf-8"))
        return (cfg.get("ntfy_topic") or "").strip()
    except Exception:
        return ""

def _notify(title, body, priority="high", tags="warning"):
    import base64
    topic = _ntfy_topic()
    if not topic:
        return
    try:
        enc = "=?utf-8?b?" + base64.b64encode(title.encode("utf-8")).decode("ascii") + "?="
        req = urllib.request.Request(f"https://ntfy.sh/{topic}",
                                     data=body.encode("utf-8"), method="POST")
        req.add_header("Title", enc)
        req.add_header("Priority", priority)
        req.add_header("Tags", tags)
        req.add_header("Content-Type", "text/plain; charset=utf-8")
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.warning(f"[ntfy] hata: {e}")


# ── SERVİS KONTROL ───────────────────────────────────────────────────────────
def _proc_list(match):
    """match ile eşleşen TÜM süreçleri döner (pid, create_time)."""
    m = match.replace("/", "\\").lower()
    found = []
    for p in psutil.process_iter(["name", "cmdline", "create_time"]):
        try:
            cl = " ".join(p.info.get("cmdline") or []).replace("/", "\\").lower()
            if m in cl:
                found.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found

def _proc_running(match):
    return len(_proc_list(match)) > 0

def _dedup(match):
    """ÇİFT KOPYA TEMİZLİĞİ: aynı servisten 2+ kopya varsa (boot yarışı:
    Run kaydı + watchdog + server bekçisi aynı anda başlatabiliyor) en
    ESKİSİNİ tutar, gerisini kapatır. Kim başlatırsa başlatsın 60 sn
    içinde teke iner."""
    procs = _proc_list(match)
    if len(procs) <= 1:
        return
    procs.sort(key=lambda p: p.info.get("create_time") or 0)
    for p in procs[1:]:
        try:
            log.warning(f"ÇİFT KOPYA: {match} (PID {p.pid}) → fazlası kapatılıyor")
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

def _launch(script, cwd):
    subprocess.Popen([PYTHONW, str(script)], cwd=str(cwd),
                     creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS)

def check_services():
    """Düşen servisleri yeniden başlatır. Döner: bu turda restart edilenler listesi."""
    restarted = []
    for match, (script, cwd) in SERVICES.items():
        if not script.exists():
            continue
        _dedup(match)          # fazla kopya varsa en eskisi kalır
        if _proc_running(match):
            continue
        # Cooldown: aynı servisi 5 dk içinde tekrar başlatma (restart loop önle)
        if time.time() - _last_restart.get(match, 0) < 300:
            continue
        log.warning(f"DÜŞMÜŞ: {match} → yeniden başlatılıyor")
        try:
            _launch(script, cwd)
            _last_restart[match] = time.time()
            restarted.append(match)
        except Exception as e:
            log.error(f"{match} başlatılamadı: {e}")
    return restarted


# ── DDE ──────────────────────────────────────────────────────────────────────
def _market_open():
    now = datetime.now()
    return now.weekday() < 5 and now.replace(hour=9, minute=55).time() <= now.time() <= now.replace(hour=18, minute=25).time()

def check_dde():
    """Piyasa açıkken DDE canlı değilse görünmez aç. Döner: (canli_mi, mudahale)."""
    if not _market_open():
        return True, False
    try:
        sys.path.insert(0, str(ROOT / "Gunluk_Al_Sat"))
        import ensure_dde
        if ensure_dde.dde_live():
            return True, False
        ok, _ = ensure_dde.ensure()
        return ok, True
    except Exception as e:
        log.debug(f"DDE kontrol hatası: {e}")
        return False, False


# ── GÜNLÜK YEDEK ─────────────────────────────────────────────────────────────
def daily_backup():
    """state.json + Firebase scoreHistory/advisor yedeği (son 14 gün tutulur)."""
    BACKUPDIR.mkdir(exist_ok=True)
    today = date.today().isoformat()
    try:
        st = ROOT / "Gunluk_Al_Sat" / "state.json"
        if st.exists():
            shutil.copy2(st, BACKUPDIR / f"state_{today}.json")
        fb = {}
        for node in ("scoreHistory", "advisor"):
            try:
                with urllib.request.urlopen(f"{FB_BASE}/{node}.json", timeout=15) as r:
                    fb[node] = json.loads(r.read().decode("utf-8"))
            except Exception:
                pass
        (BACKUPDIR / f"firebase_{today}.json").write_text(
            json.dumps(fb, ensure_ascii=False), encoding="utf-8")
        # 14 günden eski yedekleri sil
        cutoff = date.today() - timedelta(days=14)
        for f in BACKUPDIR.glob("*.json"):
            try:
                ds = f.stem.split("_")[-1]
                if date.fromisoformat(ds) < cutoff:
                    f.unlink()
            except Exception:
                pass
        log.info(f"Günlük yedek alındı: {today}")
    except Exception as e:
        log.warning(f"Yedek hatası: {e}")


# ── ANA DÖNGÜ ────────────────────────────────────────────────────────────────
def _full_check_and_report():
    """Tam kontrol; SADECE sorun varsa bildirir. (Sabah raporu + restart bildirimi)"""
    problems = []
    for match, (script, cwd) in SERVICES.items():
        if script.exists() and not _proc_running(match):
            problems.append(f"❌ {match.split(chr(92))[-1]} çalışmıyor")
    live, _ = check_dde()
    if _market_open() and not live:
        problems.append("❌ DDE canlı değil (fiyatlar gecikmeli — MatriksIQ açık mı?)")
    if problems:
        _notify("⚠️ GridTracker — Sorun Var",
                "\n".join(problems) + "\n\n(Watchdog otomatik düzeltmeye çalışıyor.)",
                priority="high", tags="warning")
        log.warning("Sabah raporu — sorunlar bildirildi: " + "; ".join(problems))
    else:
        log.info("Sabah kontrolü: her şey sağlıklı (bildirim yok).")


def main(once=False):
    log.info("Health watchdog başlatıldı.")
    _morning_done = None   # son sabah-rapor günü
    _backup_done  = None   # son yedek günü

    while True:
        try:
            check_services()
            check_dde()

            now = datetime.now()
            tdy = now.date()

            # Sabah ~09:30 raporu (günde bir, sadece sorun varsa bildirir)
            if now.hour == 9 and now.minute >= 30 and _morning_done != tdy:
                _morning_done = tdy
                _full_check_and_report()

            # Günlük yedek (her gün ~09:45)
            if now.hour == 9 and now.minute >= 45 and _backup_done != tdy:
                _backup_done = tdy
                daily_backup()

        except Exception as e:
            log.error(f"Watchdog döngü hatası: {e}")

        if once:
            return
        time.sleep(60)


if __name__ == "__main__":
    if "--once" in sys.argv:
        main(once=True)
        print("Tek tur tamamlandı.")
    else:
        main()
