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
# Kritik (ÇIK / Felaket / ACİL) uyarıları ayrı topic'e → uygulamada alarm sesi atanır
TOPIC_ALERT = _cfg.get("ntfy_topic_alert", TOPIC + "-acil")
URL       = f"https://ntfy.sh/{TOPIC}"
URL_ALERT = f"https://ntfy.sh/{TOPIC_ALERT}"

from urllib.parse import quote as _quote

FIREBASE_URL = "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app"


def _action_cmd(action: str, symbol: str, label: str) -> str:
    """ntfy bildirimi içine TEK DOKUNUŞ butonu: telefondan doğrudan Firebase'e
    Sattım/Aldım komutu yazar (monitor 4 sn'de işler). Sayfa açmaya gerek kalmaz.
    NOT: HTTP header'a gittiği için etiket/ASCII içerik kullanılır."""
    import time as _t, random, string
    aid  = f"ntfy-{int(_t.time()*1000)}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=4))}"
    body = json.dumps({"action": action, "symbol": symbol,
                       "ts": int(_t.time()*1000), "id": aid})
    url  = f"{FIREBASE_URL}/gridtracker/advisor/userAction.json"
    return (f"http, {label}, {url}, method=PUT, "
            f"headers.Content-Type=application/json, body='{body}', clear=true")


def action_sold(symbol: str) -> str:
    return _action_cmd("sold", symbol, f"SATTIM ({symbol})")


def action_bought(symbol: str) -> str:
    return _action_cmd("bought", symbol, f"ALDIM ({symbol})")


def _fp(v) -> str:
    """Fiyatı 2 ondalık (kuruş) biçimler: 2.5 → '2.50', 64 → '64.00'."""
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


def _send(title: str, body: str, priority: str = "default", tags: str = "",
          alert: bool = False, actions: str = "") -> bool:
    try:
        # alert=True → kritik topic (alarm sesi). Aksi halde normal topic.
        base = URL_ALERT if alert else URL
        # Kritik bildirimlerin başına benzersiz [ACİL] etiketi — MacroDroid/Tasker
        # gibi araçlar tek kuralla (içinde "[ACİL]" geçenler) alarm sesi çalabilir.
        if alert and "[ACİL]" not in title:
            title = f"[ACİL] {title}"
        # Başlık URL parametresi olarak geçiliyor — Türkçe karakter + emoji destekli
        url = f"{base}?title={_quote(title)}"
        headers = {"Priority": priority, "Content-Type": "text/plain; charset=utf-8"}
        if tags:
            headers["Tags"] = tags
        if actions:
            headers["Actions"] = actions   # tek-dokunuş butonu (action_sold/bought)
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
    ]
    # Giriş bölgesi — bu aralıkta girilmeli (kaçmadan)
    ez = new_pick.get("entry_zone") or {}
    if ez.get("low") and ez.get("high"):
        lines.append(f"➤ Giriş Bölgesi: {_fp(ez['low'])} – {_fp(ez['high'])} TL")
    lines += [
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
        # Kritik → alarm topic (ayrı ses) + tek dokunuş SATTIM butonu
        return _send(title, "\n".join(lines), priority="urgent",
                     tags="rotating_light", alert=True,
                     actions=action_sold(symbol))

    return False


def send_daily_pick(pick, lot=None):
    li        = lot or {}
    # KARTLA AYNI: ana giriş (lots_main) baş rakam; fırsat alımı (dip) ayrı satır.
    # (Eskiden 'lots'=toplam gösteriliyordu → bildirimdeki sayı kartla uyuşmuyordu.)
    lots_main = li.get("lots_main") or li.get("lots", 0)
    lots_dip  = li.get("lots_dip", 0)
    title = f"📊 {pick['symbol']} — Günün Önerisi"
    lines = [
        f"Skor  : {pick['total_score']:.1f} / 10",
        f"Vade  : {'Kısa (3-7 gün)' if pick['timeframe']=='KISA_VADE' else 'Orta (2-4 hafta)'}",
        f"Giriş : {_fp(pick['entry_zone']['low'])} – {_fp(pick['entry_zone']['high'])} TL",
        f"Stop  : {_fp(pick['stop_loss'])} TL",
        f"Hedef : {_fp(pick['target1'])} → {_fp(pick['target2'])} TL",
    ]
    if lots_main:
        _conv = li.get("conviction")
        lines.append(f"Ana giriş: {lots_main:,} lot".replace(",", ".") +
                     (f"  ({_conv})" if _conv else ""))
    if lots_dip:
        lines.append(f"Fırsat alımı: {lots_dip:,} lot — {_fp(li.get('dip_price', 0))} TL'ye gelirse".replace(",", "."))
    return _send(title, "\n".join(lines), tags="chart_increasing",
                 actions=action_bought(pick["symbol"]))


def send_capital_updated(capital):
    return _send("Sermaye güncellendi",
                 f"Yeni sermaye: {capital:,.0f} TL".replace(",", "."),
                 priority="min", tags="moneybag")
