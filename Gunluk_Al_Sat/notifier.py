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


def send_exit_signal(signal, symbol, score_prev, score_now, message, new_pick, lot_info):
    if signal == "DİKKAT":
        title = f"⚠️ {symbol} — Dikkat"
        body  = (f"Skor: {score_now:.1f}/10  (önceki: {score_prev:.1f})\n"
                 f"Sebep: {message}")
        return _send(title, body, priority="high", tags="warning")

    if signal in ("ÇIK", "ACİL_ÇIK"):
        title = f"ÇIKIŞ YAP — {symbol}"
        lines = [
            f"Skor  : {score_now:.1f}/10  (önceki: {score_prev:.1f})",
            f"Sebep : {message}",
        ]

        if new_pick:
            li     = (lot_info or {}).get(new_pick["symbol"], {})
            lots   = li.get("lots", 0)
            rr     = new_pick.get("rr_ratio", 0)
            escore = new_pick.get("entry_score", new_pick.get("total_score", 0))
            price  = new_pick["price"]
            stop   = new_pick["stop_loss"]
            hedef  = new_pick["target1"]
            risk_tl   = round(price - stop, 2)
            kazanc_tl = round(hedef - price, 2)

            lines += [
                "",
                f"✅ YENİ HİSSE: {new_pick['symbol']}",
                f"Giriş Skoru : {escore:.1f} / 10",
                f"Fiyat       : {price:.2f} TL",
                f"Stop        : {stop:.2f} TL",
                f"1. Hedef    : {hedef:.2f} TL",
            ]
            if rr >= 1.5:
                lines.append(
                    f"Risk/Kazanç : {risk_tl:.2f} TL kayıp → {kazanc_tl:.2f} TL kazanç ({rr:.1f}x)"
                )
            if lots:
                lines.append(f"Lot         : {lots:,} lot".replace(",", "."))

        return _send(title, "\n".join(lines), priority="urgent", tags="rotating_light")

    return False


def send_daily_pick(pick, lot=None):
    li   = lot or {}
    lots = li.get("lots", 0)
    title = f"📊 {pick['symbol']} — Günün Önerisi"
    lines = [
        f"Skor  : {pick['total_score']:.1f} / 10",
        f"Vade  : {'Kısa (3-7 gün)' if pick['timeframe']=='KISA_VADE' else 'Orta (2-4 hafta)'}",
        f"Giriş : {pick['entry_zone']['low']:.2f} – {pick['entry_zone']['high']:.2f} TL",
        f"Stop  : {pick['stop_loss']:.2f} TL",
        f"Hedef : {pick['target1']:.2f} → {pick['target2']:.2f} TL",
    ]
    if lots:
        lines.append(f"Lot   : {lots:,} lot".replace(",", "."))
    return _send(title, "\n".join(lines), tags="chart_increasing")


def send_capital_updated(capital):
    return _send("Sermaye güncellendi",
                 f"Yeni sermaye: {capital:,.0f} TL".replace(",", "."),
                 priority="min", tags="moneybag")
