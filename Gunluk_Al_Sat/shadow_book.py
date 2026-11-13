"""
shadow_book.py — GÖLGE KARNE (2026-11-10): sistem sürümlerini CANLI piyasada sanal olarak yarıştırır.

Her işlem günü akşamı (advisor 18:35'ten sonra, cron 18:50) çalışır:
  1) Önceki akşam karar verilen sanal alımlar bugünün AÇILIŞ fiyatından girilir
  2) Açık sanal pozisyonlar bugünün mumu ile yönetilir (VK3: hedef %5, stop %7, 3 gün)
  3) Boştaki sürümler bu akşamki öneri listesinden (advisor_result.json) kendi kuralıyla seçer
Cuma akşamı (veya --report) haftalık karne bildirimi gönderir; özet Firebase gridtracker/shadow'a yazılır.
Her işlem sabit 50.000 TL ile hesaplanır (sürümler adil karşılaştırılsın diye).

Kullanım: python shadow_book.py            (akşam çalışması)
          python shadow_book.py --report   (karneyi şimdi gönder)
          python shadow_book.py --show     (karneyi ekrana yaz, bildirim yok)
"""
import json, math, sys
from datetime import datetime, date
from pathlib import Path

import numpy as np

BASE = Path(__file__).parent
BOOK = BASE / "shadow_book.json"
CAPITAL, COMM = 50_000.0, 0.0004
TGT, STOP, HOLD = 5.0, 7.0, 3
FB = "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app/gridtracker/shadow.json"

# Yarışan sürümler. index: XU100<SMA20 iken alım yok | sold: satılan hisse kuralı
# events: bilanço/temettü günü yakın hisseyi alma (olay filtresi)
VARIANTS = {
    "canli":     {"ad": "Canlı (endeks + satılanı alma + olay)", "index": True,  "sold": "skip", "events": True},
    "olaysiz":   {"ad": "Olay filtresi yok",                     "index": True,  "sold": "skip", "events": False},
    "endekssiz": {"ad": "Endeks filtresi yok",                   "index": False, "sold": "skip", "events": True},
    "bekle":     {"ad": "Satıştan sonra 1 gün bekle",            "index": True,  "sold": "wait", "events": True},
    "eski_vk3":  {"ad": "Eski VK3 (filtresiz)",                  "index": False, "sold": "none", "events": False},
}


def load_book():
    try:
        b = json.loads(BOOK.read_text(encoding="utf-8"))
    except Exception:
        b = {"start": date.today().isoformat(), "variants": {}}
    for k in VARIANTS:
        b["variants"].setdefault(k, {"pos": None, "pending": None, "trades": [], "last_exit": None})
    return b


def save_book(b):
    BOOK.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")


def bars(sym, period="1mo"):
    import yfinance as yf
    df = yf.download(f"{sym}.IS", period=period, interval="1d", progress=False, auto_adjust=False)
    if df is None or df.empty:
        return None
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    df.index = [d.strftime("%Y-%m-%d") for d in df.index]
    return df.dropna(subset=["Open", "High", "Low", "Close"])


def busdays(a, b):
    return int(np.busday_count(a, b))


def manage(v, today, bar, log):
    """Açık pozisyonu bugünün mumu ile yönet. Çıkış olursa işlemi kaydeder."""
    p = v["pos"]
    o, h, l, c = (float(bar[k]) for k in ("Open", "High", "Low", "Close"))
    held = busdays(p["entry_date"], today); gap = held > 0; ex = why = None
    if l <= p["stop"]:
        ex, why = (min(p["stop"], o) if gap else p["stop"]), "stop"
    elif h >= p["tgt"]:
        ex, why = (max(p["tgt"], o) if gap else p["tgt"]), "hedef"
    elif held >= HOLD:
        ex, why = c, "süre"
    if ex is None:
        p["last"] = c          # karnede açık pozisyonun anlık K/Z'si için
        return
    pnl = (ex - p["entry"]) * p["qty"] - COMM * (ex + p["entry"]) * p["qty"]
    v["trades"].append({"sym": p["sym"], "in": p["entry_date"], "entry": round(p["entry"], 4), "qty": p["qty"],
                        "out": today, "exit": round(ex, 4), "why": why, "pnl": round(pnl, 2)})
    v["last_exit"] = {"date": today, "sym": p["sym"]}
    v["pos"] = None
    log.append(f"{p['sym']} çıkış {why} {ex:.2f} → {pnl:+.0f} TL")


def event_blocked(sym, today):
    try:
        import events
        return events.blocked(sym, today)
    except Exception:
        return None


def run():
    today = date.today().isoformat()
    xu = bars("XU100", "3mo")
    if xu is None or xu.index[-1] != today:
        print(f"[Gölge] {today} işlem günü değil / veri yok — çıkıldı"); return
    xc = xu["Close"].astype(float)
    index_ok = float(xc.iloc[-1]) >= float(xc.iloc[-20:].mean())

    try:
        res = json.loads((BASE.parent / "advisor_result.json").read_text(encoding="utf-8"))
    except Exception:
        res = {}
    res_today = datetime.fromtimestamp(res.get("ts", 0)).date().isoformat() == today
    picks = [p["symbol"] for p in (res.get("top_picks") or [])] if res_today else []

    b = load_book()
    if b.get("last_run") == today:
        print("[Gölge] bugün zaten çalıştı"); return
    cache = {}
    def bar_of(sym):
        if sym not in cache:
            cache[sym] = bars(sym)
        df = cache[sym]
        return None if df is None or today not in df.index else df.loc[today]

    for k, cfg in VARIANTS.items():
        v = b["variants"][k]; log = []
        # 1) bekleyen alım → bugün açılıştan gir
        if v["pending"] and not v["pos"]:
            bar = bar_of(v["pending"]["sym"])
            if bar is not None:
                e = float(bar["Open"]); q = math.floor(CAPITAL / e)
                v["pos"] = {"sym": v["pending"]["sym"], "entry_date": today, "entry": e, "qty": q,
                            "stop": e * (1 - STOP / 100), "tgt": e * (1 + TGT / 100)}
                log.append(f"ALIŞ {v['pending']['sym']} {q} lot @ {e:.2f}")
            v["pending"] = None
        # 2) açık pozisyonu yönet
        if v["pos"]:
            bar = bar_of(v["pos"]["sym"])
            if bar is not None:
                manage(v, today, bar, log)
        # 3) boştaysa bu akşamın listesinden seç
        if not v["pos"] and picks:
            lx = v.get("last_exit") or {}
            just_sold = lx.get("date") == today
            ok = not (cfg["index"] and not index_ok) and not (cfg["sold"] == "wait" and just_sold)
            if ok:
                for s in picks:
                    if cfg["sold"] == "skip" and just_sold and s == lx.get("sym"):
                        continue
                    if cfg["events"] and event_blocked(s, today):
                        log.append(f"{s} olay filtresine takıldı"); continue
                    v["pending"] = {"sym": s, "decided": today}
                    log.append(f"karar: yarın {s} al"); break
        if log:
            print(f"[Gölge] {cfg['ad']}: " + " | ".join(log))
    b["last_run"] = today
    save_book(b)
    push_firebase(b)
    if date.today().weekday() == 4:
        report(b, send=True)


def summary(b):
    out = []
    week0 = date.fromordinal(date.today().toordinal() - date.today().weekday()).isoformat()
    for k, cfg in VARIANTS.items():
        v = b["variants"][k]; tr = v["trades"]
        tot = sum(t["pnl"] for t in tr); wk = sum(t["pnl"] for t in tr if t["out"] >= week0)
        wins = sum(1 for t in tr if t["pnl"] > 0)
        p = v["pos"] or {}
        acik_kz = round((p["last"] - p["entry"]) * p["qty"]) if p.get("last") else 0
        out.append({"key": k, "ad": cfg["ad"], "toplam": round(tot), "hafta": round(wk), "islem": len(tr),
                    "isabet": round(wins / len(tr) * 100) if tr else None,
                    "acik": p.get("sym"), "acik_kz": acik_kz, "acik_giris": round(p.get("entry", 0), 2),
                    "bekleyen": (v["pending"] or {}).get("sym")})
    return out


def push_firebase(b):
    try:
        import requests
        requests.put(FB, json={"start": b["start"], "updated": datetime.now().strftime("%d.%m.%Y %H:%M"),
                               "summary": summary(b)}, timeout=8)
    except Exception as e:
        print(f"[Gölge] Firebase: {e}")


def report(b, send=False):
    rows = sorted(summary(b), key=lambda r: -(r["toplam"] + r["acik_kz"]))
    f = lambda n: f"{n:+,.0f}".replace(",", ".")
    lines = [f"Başlangıç: {datetime.fromisoformat(b['start']).strftime('%d.%m.%Y')} (her işlem 50.000 TL, sanal)",
             "Kapanan = satılmış işlemler · Açık = henüz satılmamış pozisyonun anlık K/Z'si",
             "━━━━━━━━━━━━━━━━━━━━"]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. {r['ad']}\n   kapanan {f(r['toplam'])} TL ({r['islem']} işlem"
                     + (f", isabet %{r['isabet']}" if r["isabet"] is not None else "") + ")"
                     + (f"\n   açık: {r['acik']} @ {r['acik_giris']:.2f} → {f(r['acik_kz'])} TL".replace(".", ",", 1) if r["acik"] else ""))
    text = "\n".join(lines)
    print(text)
    if send:
        try:
            import notifier
            notifier._send("📊 Haftalık Gölge Karne", text, priority="default", tags="bar_chart")
        except Exception as e:
            print(f"[Gölge] bildirim: {e}")


if __name__ == "__main__":
    if "--report" in sys.argv:
        report(load_book(), send=True)
    elif "--show" in sys.argv:
        report(load_book())
    else:
        run()
