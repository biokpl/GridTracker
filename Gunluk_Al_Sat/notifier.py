"""
notifier.py — Kısa, net, Türkçe push bildirimleri (ntfy.sh)
"""
import json
import sys
import requests
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_cfg  = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
TOPIC = _cfg.get("ntfy_topic", "GridTracker-bkpl-07")
URL   = f"https://ntfy.sh/{TOPIC}"

from urllib.parse import quote as _quote


def _fp(v) -> str:
    """Fiyatı gereksiz sıfır olmadan biçimler: 64.0 → '64', 2.73 → '2.73'."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{f:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _send(title: str, body: str, priority: str = "default", tags: str = "") -> bool:
    try:
        # Başlık URL parametresi olarak geçiliyor — Türkçe karakter + emoji destekli
        url = f"{URL}?title={_quote(title)}"
        headers = {"Priority": priority, "Content-Type": "text/plain; charset=utf-8"}
        if tags:
            headers["Tags"] = tags
        r = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=10)
        ok = r.status_code == 200
        print(f"[Push] {'OK' if ok else 'HATA'}: {title}")
        return ok
    except Exception as e:
        print(f"[Push] Bağlantı hatası: {e}")
        return False


def _new_pick_lines(new_pick, lot_info, baslik="✅ YENİ HİSSE"):
    """Yeni hisse öneri satırlarını oluşturur."""
    li        = (lot_info or {}).get(new_pick["symbol"], {})
    lots      = li.get("lots", 0)
    rr        = new_pick.get("rr_ratio", 0)
    escore    = new_pick.get("entry_score", new_pick.get("total_score", 0))
    price     = new_pick["price"]
    stop      = new_pick["stop_loss"]
    hedef     = new_pick["target1"]
    risk_tl   = round(price - stop, 2)
    kazanc_tl = round(hedef - price, 2)

    lines = [
        "",
        f"{baslik}: {new_pick['symbol']}",
    ]
    # Lot üste, altı çizili görünüm
    if lots:
        lines.append(f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
        lines.append(f"Giriş Lot Miktarı : {lots:,} lot".replace(",", "."))
        lines.append(f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
    lines += [
        f"Giriş Skoru : {escore:.1f} / 10",
        f"Fiyat       : {_fp(price)} TL",
        f"Stop        : {_fp(stop)} TL",
        f"1. Hedef    : {_fp(hedef)} TL",
    ]
    if rr >= 1.5:
        lines.append(
            f"Risk/Kazanç : {_fp(risk_tl)} TL kayıp → {_fp(kazanc_tl)} TL kazanç ({rr:.1f}x)"
        )
    return lines


def send_exit_signal(signal, symbol, score_prev, score_now, message, new_pick, lot_info):
    if signal == "DİKKAT":
        title = f"⚠️ {symbol} — Dikkat"
        body  = (f"Skor: {score_now:.1f}/10  (önceki: {score_prev:.1f})\n"
                 f"Sebep: {message}")
        return _send(title, body, priority="high", tags="warning")

    if signal == "DEĞİŞTİR":
        title = f"🔄 GEÇİŞ ÖNERİSİ — {symbol}"
        lines = [
            f"Mevcut hisse DEVAM ediyor ancak daha iyi fırsat var.",
            f"Sebep: {message}",
        ]
        if new_pick:
            lines += _new_pick_lines(new_pick, lot_info, baslik="💡 ÖNERİLEN HİSSE")
        return _send(title, "\n".join(lines), priority="default", tags="arrows_counterclockwise")

    if signal in ("ÇIK", "ACİL_ÇIK"):
        title = f"ÇIKIŞ YAP — {symbol}"
        lines = [
            f"Skor  : {score_now:.1f}/10  (önceki: {score_prev:.1f})",
            f"Sebep : {message}",
        ]
        if new_pick:
            lines += _new_pick_lines(new_pick, lot_info)
        return _send(title, "\n".join(lines), priority="urgent", tags="rotating_light")

    return False


def send_daily_pick(pick, lot=None):
    li   = lot or {}
    lots = li.get("lots", 0)
    title = f"📊 {pick['symbol']} — Günün Önerisi"
    lines = [
        f"Skor  : {pick['total_score']:.1f} / 10",
        f"Vade  : {'Kısa (3-7 gün)' if pick['timeframe']=='KISA_VADE' else 'Orta (2-4 hafta)'}",
        f"Giriş : {_fp(pick['entry_zone']['low'])} – {_fp(pick['entry_zone']['high'])} TL",
        f"Stop  : {_fp(pick['stop_loss'])} TL",
        f"Hedef : {_fp(pick['target1'])} → {_fp(pick['target2'])} TL",
    ]
    if lots:
        lines.append(f"Lot   : {lots:,} lot".replace(",", "."))
    return _send(title, "\n".join(lines), tags="chart_increasing")


def send_capital_updated(capital):
    return _send("Sermaye güncellendi",
                 f"Yeni sermaye: {capital:,.0f} TL".replace(",", "."),
                 priority="min", tags="moneybag")
