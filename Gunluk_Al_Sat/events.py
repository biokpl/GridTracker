"""
events.py — OLAY FİLTRESİ (2026-11-10): bilanço / temettü günü elde tutma süresine denk gelen hisseyi alma.

5 yıllık test: bilanço açıklaması elde tutarken (ertesi 4 seans) düşen işlemler ort. %-0,79
(bilanço olmayan %+0,32), stop oranı %17. Temettü kesim günü fiyatı aşağı boşluklu açar,
stopu/hedefi bozar. Kaynak: Yahoo (bilanço tarihi ~%55 hisse için var; yoksa engellenmez).

blocked(sym, today) → engel nedeni (str) ya da None. Sonuçlar hisse başına 3 gün önbelleklenir.
"""
import json, time
from datetime import date
from pathlib import Path

import numpy as np

CACHE = Path(__file__).parent / "events_live.json"
TTL = 3 * 86400
WINDOW = 5          # ertesi sabah alış + en fazla 4 seans elde tutma


def _load():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _fetch(sym):
    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf
    t = yf.Ticker(f"{sym}.IS"); earn, div = [], []
    try:
        ed = t.get_earnings_dates(limit=6)
        if ed is not None:
            earn = sorted({str(x.date()) for x in ed.index})
    except Exception:
        pass
    try:
        cal = t.calendar or {}
        for k in ("Earnings Date",):
            v = cal.get(k)
            for d in (v if isinstance(v, list) else [v]):
                if d: earn = sorted(set(earn) | {str(d)})
        if cal.get("Ex-Dividend Date"):
            div = [str(cal["Ex-Dividend Date"])]
    except Exception:
        pass
    return {"earn": earn, "div": div, "ts": time.time()}


def info(sym):
    c = _load(); e = c.get(sym)
    if not e or time.time() - e.get("ts", 0) > TTL:
        e = _fetch(sym); c[sym] = e
        try:
            CACHE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    return e


def blocked(sym, today=None):
    today = today or date.today().isoformat()
    end = str(np.busday_offset(today, WINDOW, roll="forward"))
    e = info(sym)
    for d in e.get("earn", []):
        if today < d <= end:
            return f"bilanço {d}"
    for d in e.get("div", []):
        if today < d <= end:
            return f"temettü kesimi {d}"
    return None


if __name__ == "__main__":
    import sys
    for s in sys.argv[1:] or ["GARAN", "THYAO", "ASELS", "TUPRS"]:
        print(s, info(s), "→", blocked(s) or "serbest")
