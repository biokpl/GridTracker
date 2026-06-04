"""
tracker.py — 1.xlsx al/sat kayıtlarından aktif pozisyon P&L hesabı.
Çağrı: track(state: dict) -> dict
"""
import json
from datetime import datetime
from pathlib import Path

import openpyxl
import yfinance as yf

_cfg = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
EXCEL_PATH  = Path(_cfg["excel_path"])
COMM_RATE   = _cfg["commission_rate"]
_FB_TRADES  = ("https://grid-tracker-73ed2-default-rtdb.europe-west1."
               "firebasedatabase.app/gridtracker/allTrades.json")


def _read_trades_firebase(symbol: str, day: str = None):
    """
    Firebase 'allTrades'ten verilen sembol için (varsayılan: bugün) Alış/Satış
    listelerini döndürür. grid_tracker_service 1.xlsx'i işleyip SİLDİĞİ için
    advisor dosyayı bulamıyordu; kalıcı kaynak Firebase'tir.
    """
    import urllib.request
    if day is None:
        day = datetime.now().strftime("%Y-%m-%d")
    try:
        with urllib.request.urlopen(_FB_TRADES, timeout=15) as r:
            at = json.loads(r.read().decode("utf-8")) or []
    except Exception:
        return [], []
    if isinstance(at, dict):
        at = list(at.values())
    if not isinstance(at, list):
        return [], []
    buys, sells = [], []
    for t in at:
        if not isinstance(t, dict):
            continue
        if str(t.get("date", ""))[:10] != day:
            continue
        if str(t.get("symbol", "")).upper() != symbol.upper():
            continue
        qty = int(t.get("execQty") or t.get("qty") or 0)
        px  = _sf(t.get("execPrice") or t.get("price") or 0)
        amt = _sf(t.get("execAmount") or t.get("amount") or (qty * px))
        comm = _sf(t.get("commission") or round(amt * COMM_RATE, 4))
        rec = {"symbol": symbol.upper(), "date": str(t.get("date", ""))[:10],
               "datetime": t.get("datetime", ""), "time": t.get("time", ""),
               "execQty": qty, "execPrice": px, "execAmount": amt, "commission": comm}
        typ = _ss(t.get("type", ""))
        if "Alı" in typ or "Alis" in typ:
            buys.append(rec)
        elif "Sat" in typ:
            sells.append(rec)
    return buys, sells


def _sf(v):
    try: return float(v)
    except: return 0.0


def _ss(v):
    if v is None: return ""
    return str(v).strip()


def _read_excel(symbol: str) -> tuple[list, list]:
    """Verilen sembol için Alış/Satış listelerini döndürür.
    Önce 1.xlsx; dosya yoksa (servis sildiyse) Firebase allTrades'e düşer."""
    if not EXCEL_PATH.exists():
        return _read_trades_firebase(symbol)

    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    buys, sells = [], []

    for i, r in enumerate(rows):
        if i == 0 or not r[5]:
            continue
        sym = _ss(r[5]).upper()
        if sym != symbol.upper():
            continue
        trade_type = _ss(r[7])  # 'Alış' veya 'Satış'

        raw_dt = r[21]
        if isinstance(raw_dt, datetime):
            date_s = raw_dt.strftime('%Y-%m-%d')
            dt_s   = raw_dt.strftime('%Y-%m-%d %H:%M:%S')
        else:
            s = _ss(raw_dt); date_s = s[:10]; dt_s = s[:19]

        raw_t = r[19]
        time_s = raw_t.strftime('%H:%M:%S') if isinstance(raw_t, datetime) else _ss(raw_t)[:8]

        exec_qty  = _sf(r[12]) or _sf(r[8])
        exec_price= _sf(r[16]) or _sf(r[9])
        exec_amt  = _sf(r[18]) or _sf(r[14])
        comm      = round(exec_amt * COMM_RATE, 4)

        rec = {
            "symbol":    sym,
            "date":      date_s,
            "datetime":  dt_s,
            "time":      time_s,
            "execQty":   int(exec_qty),
            "execPrice": exec_price,
            "execAmount":exec_amt,
            "commission":comm,
        }
        if "Alış" in trade_type:
            buys.append(rec)
        elif "Satış" in trade_type:
            sells.append(rec)

    wb.close()
    return buys, sells


def _current_price(symbol: str) -> float:
    """Anlık fiyat: DDE Excel → Yahoo → cache (price_reader üzerinden)."""
    try:
        from price_reader import get_price
        p, _src = get_price(symbol)
        if p and p > 0:
            return float(p)
    except Exception:
        pass
    # Son çare: doğrudan Yahoo
    try:
        t = yf.Ticker(f"{symbol}.IS")
        hist = t.history(period="2d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except:
        pass
    return 0.0


def track(state: dict) -> dict:
    """
    state: state.json içeriği
    Döndürür: tracker bloğu (advisor_result.json'a gömülür)
    """
    result = {
        "active_symbol":   None,
        "avg_cost":        0.0,
        "total_qty":       0,
        "current_price":   0.0,
        "unrealized_pnl":  0.0,
        "unrealized_pct":  0.0,
        "realized_pnl":    0.0,
        "history_pnl_total": 0.0,
        "trade_count":     0,
        "stop_loss":       0.0,
        "hard_stop":       0.0,
        "target1":         0.0,
        "target2":         0.0,
        "error":           None,
    }

    # Geçmiş toplam P&L (state.json history'den)
    history_total = sum(h.get("pnl_tl", 0) for h in state.get("history", []))
    result["history_pnl_total"] = round(history_total, 2)
    result["trade_count"] = len(state.get("history", []))

    active = state.get("active")
    if not active:
        return result

    # Stop/Hedef seviyeleri (state.json'dan) — SASA gibi top_picks'te olmayan
    # aktif pozisyonlar için kartta gösterilsin
    result["stop_loss"] = active.get("stop_loss", 0) or 0
    result["hard_stop"] = active.get("hard_stop", 0) or 0
    result["target1"]   = active.get("target1", 0) or 0
    result["target2"]   = active.get("target2", 0) or 0

    symbol = active["symbol"]
    result["active_symbol"] = symbol

    buys, sells = _read_excel(symbol)

    if buys:
        # ── Excel'den oku (GridTracker bot işlemleri) ──────────────────────
        total_qty   = sum(b["execQty"] for b in buys)
        total_cost  = sum(b["execAmount"] + b["commission"] for b in buys)
        avg_cost    = total_cost / total_qty if total_qty else 0
        sold_qty    = sum(s["execQty"] for s in sells)
        sell_amount = sum(s["execAmount"] - s["commission"] for s in sells)
        cost_of_sold= avg_cost * sold_qty
        realized    = sell_amount - cost_of_sold
        open_qty    = total_qty - sold_qty
        data_source = "excel"
    else:
        # ── Manuel giriş (SASA gibi) — alış state.json'dan, AMA satışlar
        #    yine 1.xlsx'ten okunur (kullanıcı satarsa sistem görsün) ────────
        total_qty   = active.get("qty", 0)
        avg_cost    = active.get("entry_price", 0.0)
        total_cost  = total_qty * avg_cost * (1 + COMM_RATE)
        sold_qty    = sum(s["execQty"] for s in sells)
        sell_amount = sum(s["execAmount"] - s["commission"] for s in sells)
        cost_of_sold= avg_cost * sold_qty
        realized    = sell_amount - cost_of_sold
        open_qty    = total_qty - sold_qty
        data_source = "manual"

    # Anlık fiyat
    cur_price = _current_price(symbol)

    # Unrealized P&L
    if open_qty > 0 and cur_price > 0 and avg_cost > 0:
        unrealized     = (cur_price - avg_cost) * open_qty
        unrealized_pct = (cur_price - avg_cost) / avg_cost * 100
    else:
        unrealized     = 0.0
        unrealized_pct = 0.0

    result.update({
        "avg_cost":       round(avg_cost, 4),
        "total_qty":      total_qty,
        "open_qty":       open_qty,
        "current_price":  round(cur_price, 4),
        "unrealized_pnl": round(unrealized, 2),
        "unrealized_pct": round(unrealized_pct, 2),
        "realized_pnl":   round(realized, 2),
        "data_source":    data_source,
    })
    return result


if __name__ == "__main__":
    state = json.loads((Path(__file__).parent / "state.json").read_text(encoding="utf-8"))
    r = track(state)
    print(json.dumps(r, ensure_ascii=False, indent=2))
