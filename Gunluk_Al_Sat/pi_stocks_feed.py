"""
pi_stocks_feed.py — GEÇİCİ Raspberry Pi dönemi (2026-10-25): PC'deki server.py'nin
Firebase gridtracker/stocks beslemesinin yerine geçer (yalnız AL/SAT için gereken kısım).

Önerilen ilk 3 hisse + açık pozisyon için Yahoo fiyatını gridtracker/stocks/{SYM}'e PATCH eder
(diğer alanlar — ATR, destek/direnç — korunur). Kart bunu "girilebilir / stop altında"
kontrolü için okur. systemd timer ile borsa saatlerinde 2 dk'da bir çalışır.

Kullanım: python pi_stocks_feed.py           (borsa kapalıysa hiçbir şey yapmaz)
          python pi_stocks_feed.py --force   (test)
"""
import json, sys, time
from datetime import datetime
from pathlib import Path
import requests

BASE = Path(__file__).parent
FB = "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app/gridtracker"
sys.path.insert(0, str(BASE))


def market_open(now=None):
    now = now or datetime.now()
    return now.weekday() < 5 and (9 * 60 + 55) <= now.hour * 60 + now.minute <= (18 * 60 + 15)


def symbols():
    out = set()
    try:
        from advisor import RESULT_PATH
        d = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        out |= {p["symbol"] for p in (d.get("top_picks") or [])[:3] if p.get("symbol")}
    except Exception:
        pass
    try:
        a = json.loads((BASE / "state.json").read_text(encoding="utf-8")).get("active") or {}
        if a.get("symbol"):
            out.add(a["symbol"])
    except Exception:
        pass
    return sorted(out)


def main():
    if "--force" not in sys.argv and not market_open():
        return
    from price_reader import get_price_from_yahoo
    now = int(time.time())
    for s in symbols():
        p = get_price_from_yahoo(s)
        if p and p > 0:
            requests.patch(f"{FB}/stocks/{s}.json", timeout=10,
                           json={"price": round(p, 4), "src": "yahoo", "stale": False, "price_ts": now, "live": False})
            print(f"{s} {p:.2f}")
    requests.put(f"{FB}/stocks_ts.json", data=str(now), timeout=10)


if __name__ == "__main__":
    main()
