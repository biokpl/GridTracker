"""
notifier.py — Net, anlaşılır Türkçe push bildirimleri (ntfy.sh)
"""
import json
import sys
import requests
from pathlib import Path

# Windows terminali UTF-8 yapılıyor (emoji/Türkçe karakter için)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_cfg   = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
TOPIC  = _cfg.get("ntfy_topic", "GridTracker-bkpl-07")
URL    = f"https://ntfy.sh/{TOPIC}"

# Türkçe → ASCII (HTTP başlıkları için)
_TR = str.maketrans("ğĞşŞıİçÇöÖüÜ", "gGsSiIcCooUU")

def _ascii(s: str) -> str:
    return s.translate(_TR)

def _fmt_tl(v: float) -> str:
    if v >= 1_000_000: return f"{v/1_000_000:.2f}M TL"
    if v >= 1_000:     return f"{v/1_000:.1f}K TL"
    return f"{v:.2f} TL"

_EMOJI = str.maketrans({c: "" for c in "🔴🚨⚠️📊✅🧠📌▲▼💰"})

def _clean_title(s: str) -> str:
    """HTTP başlığına uygun: emoji yok, Türkçe karakter yok."""
    return _ascii(s).translate(_EMOJI).strip()


def _send_raw(title: str, body: str, priority: str = "default", tags: str = "") -> bool:
    try:
        headers = {
            "Title":        _clean_title(title),
            "Priority":     priority,
            "Content-Type": "text/plain; charset=utf-8",
        }
        if tags:
            headers["Tags"] = tags
        r = requests.post(URL, data=body.encode("utf-8"), headers=headers, timeout=10)
        ok = r.status_code == 200
        if ok:
            print(f"[Push] Gönderildi: {title}")
        else:
            print(f"[Push] Hata {r.status_code}: {r.text[:100]}")
        return ok
    except Exception as e:
        print(f"[Push] Bağlantı hatası: {e}")
        return False


def _tf_label(tf: str) -> str:
    if tf == "KISA_VADE": return "Kısa Vade (3-7 gün)"
    if tf == "ORTA_VADE": return "Orta Vade (2-4 hafta)"
    return tf


# ─── Bildirim Fonksiyonları ───────────────────────────────────────────────────

def send_exit_signal(signal: str, symbol: str, score_prev: float, score_now: float,
                     message: str, new_pick: dict | None, lot_info: dict) -> bool:
    """
    ÇIKIŞ veya DİKKAT bildirimi.
    Çıkış varsa yeni hisse ve lot bilgisini de içerir.
    """
    if signal == "DİKKAT":
        title = f"⚠️ DİKKAT: {symbol} ZAYIFLIYOR"
        body_lines = [
            f"Hisse: {symbol}",
            f"Skor: {score_prev:.1f} → {score_now:.1f} / 10",
            f"Durum: {message}",
            "─" * 28,
            "🔍 Yakından izleyin, çıkış sinyali yaklaşıyor.",
        ]
        return _send_raw(title, "\n".join(body_lines), priority="high", tags="warning")

    elif signal in ("ÇIK", "ACİL_ÇIK"):
        urgency = "🚨 ACİL" if signal == "ACİL_ÇIK" else "🔴"
        title = f"{urgency} ÇIKIŞ YAP: {symbol}"

        body_lines = [
            f"══ ÇIKIŞ SİNYALİ ══",
            f"Hisse      : {symbol}",
            f"Skor       : {score_prev:.1f} → {score_now:.1f} / 10",
            f"Sebep      : {message}",
            "",
        ]

        if new_pick:
            nli   = lot_info.get(new_pick["symbol"], {})
            lots  = nli.get("lots", 0)
            cost  = nli.get("cost", 0)
            np_price_lo = new_pick["entry_zone"]["low"]
            np_price_hi = new_pick["entry_zone"]["high"]

            body_lines += [
                f"══ YENİ HİSSE: {new_pick['symbol']} ══",
                f"Skor       : {new_pick['total_score']:.1f} / 10",
                f"Vade       : {_tf_label(new_pick['timeframe'])}",
                f"Giriş Bölg.: {np_price_lo:.2f} – {np_price_hi:.2f} TL",
                f"Stop Loss  : {new_pick['stop_loss']:.2f} TL",
                f"1. Hedef   : {new_pick['target1']:.2f} TL",
                f"2. Hedef   : {new_pick['target2']:.2f} TL",
            ]
            if lots > 0:
                body_lines += [
                    "",
                    f"Alabileceğiniz Lot: {lots:,} lot",
                    f"Tahmini Maliyet   : {_fmt_tl(cost)}",
                ]
            body_lines += [
                "",
                f"Neden: {new_pick['reasoning']}",
            ]

        pri  = "urgent" if signal == "ACİL_ÇIK" else "urgent"
        tags = "rotating_light" if signal == "ACİL_ÇIK" else "red_circle,arrow_right"
        return _send_raw(title, "\n".join(body_lines), priority=pri, tags=tags)

    return False


def send_daily_pick(pick: dict, lot: dict | None = None) -> bool:
    """
    Aktif pozisyon yoksa günlük en iyi öneri bildirimi.
    """
    li    = lot or {}
    lots  = li.get("lots", 0)
    cost  = li.get("cost", 0)
    title = f"📊 GÜNÜN ÖNERİSİ: {pick['symbol']}"

    body_lines = [
        f"══ SATIN AL: {pick['symbol']} ══",
        f"Skor       : {pick['total_score']:.1f} / 10",
        f"Vade       : {_tf_label(pick['timeframe'])}",
        f"Giriş Bölg.: {pick['entry_zone']['low']:.2f} – {pick['entry_zone']['high']:.2f} TL",
        f"Stop Loss  : {pick['stop_loss']:.2f} TL",
        f"1. Hedef   : {pick['target1']:.2f} TL",
        f"2. Hedef   : {pick['target2']:.2f} TL",
    ]
    if lots > 0:
        body_lines += [
            "",
            f"Alabileceğiniz Lot: {lots:,} lot",
            f"Tahmini Maliyet   : {_fmt_tl(cost)}",
        ]
    body_lines += [
        "",
        f"Analiz: {pick['reasoning']}",
    ]

    return _send_raw(title, "\n".join(body_lines), priority="default", tags="chart_increasing")


def send_monitor_ok(symbol: str, score: float, rsi: float) -> bool:
    """Monitor döngüsü — DEVAM sinyali (sessiz, log amaçlı)."""
    # Sadece log, push gönderme
    print(f"[Monitor] {symbol}: Skor {score:.1f}/10 | RSI {rsi:.0f} | DEVAM")
    return True


def send_capital_updated(capital: float) -> bool:
    title = "Sermaye Guncellendi"
    body  = f"Yeni sermaye: {_fmt_tl(capital)}\nBir sonraki analizde kullanılacak."
    return _send_raw(title, body, priority="min", tags="moneybag")
