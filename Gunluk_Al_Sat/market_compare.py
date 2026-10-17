"""
market_compare.py — Aynı AL/SAT stratejisini BIST ve KRİPTO'da yan yana test eder.

Soru: "50 bin TL, işlem başı ≤1.000 TL (stop) / ≤1.500 TL (felaket stop) risk
kuralıyla hangi piyasa daha çok kazandırırdı?"

• Skorlama çekirdeği backtest.py ile AYNI (advisor.score_stock + geçmişe uygun
  _weekly_trend / nötr _event_risk yaması). Kripto için endeks = BTC-USD.
• Canlı eşikler: bb<0.65, rsi<65, R/K≥1.0, entry≥3.0, max_hold=5 bar, rejim filtresi.
• Lot = canlı advisor ile aynı: sermaye × min(rejim, konviksiyon) dozu, sonra
  stopta ≤RISK, felaket stopta ≤MAX_LOSS kısıtı. K/Z TL olarak, BİLEŞİKSİZ
  (her işlem 50 bin bazından) — "ayda kaç TL" sorusuna doğrudan cevap.
• Komisyon: BIST on binde 1, kripto binde 1 (tipik spot taker).
• Çıkış: stop'a değdi → stop fiyatı, hedef → hedef fiyatı (kayma YOK — iki
  piyasa için de iyimser; kriptoda ani çöküşte kayma daha büyük olur).

Kullanım:  python market_compare.py
"""
import sys, json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
import backtest            # yamaları (weekly_trend/event_risk) uygular
import advisor

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
CAPITAL  = 50_000.0
RISK_TL  = float(CFG.get("risk_per_trade_tl") or 1000)
MAX_LOSS = float(CFG.get("max_loss_tl") or 1500)

CRYPTO = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX", "AVAX", "LINK",
          "DOT", "LTC", "BCH", "XLM", "ATOM", "ETC", "NEAR", "FIL", "UNI", "AAVE",
          "HBAR", "ICP", "ALGO", "VET", "INJ", "APT", "ARB", "OP", "SUI", "SHIB"]


def _split(raw, tickers, names, min_len=80):
    data = {}
    for t, n in zip(tickers, names):
        try:
            df = raw.xs(t, axis=1, level=1) if isinstance(raw.columns, pd.MultiIndex) else raw
            df = df.dropna(how="all")
            if len(df) >= min_len:
                data[n] = df
        except Exception:
            pass
    return data


def load_bist():
    syms = CFG["bist100"]
    tk = [f"{s}.IS" for s in syms] + ["XU100.IS"]
    raw = yf.download(tk, period="2y", interval="1d", auto_adjust=True, progress=False, threads=True)
    return _split(raw, tk, syms + ["XU100"]), syms, CFG["sectors"], 0.0001


def load_crypto():
    tk = [f"{s}-USD" for s in CRYPTO]
    raw = yf.download(tk, period="2y", interval="1d", auto_adjust=True, progress=False, threads=True)
    data = _split(raw, tk, CRYPTO)
    if "BTC" in data:
        data["XU100"] = data["BTC"].copy()          # piyasa endeksi = BTC
    syms = [s for s in CRYPTO if s in data]
    sectors = {"Büyük": ["BTC", "ETH", "BNB", "SOL", "XRP", "TRX", "ADA", "LTC", "BCH"],
               "Altcoin": [s for s in syms if s not in
                           ("BTC", "ETH", "BNB", "SOL", "XRP", "TRX", "ADA", "LTC", "BCH")]}
    return data, syms, sectors, 0.001


def simulate(data, syms, sectors, comm, bb_max=0.65, rsi_max=65.0, rr_min=1.0,
             entry_min=3.0, max_hold=5, warmup=65):
    xu = data["XU100"]
    idx = xu.index
    trades, cooldown, pos = [], {}, None
    for t in range(warmup, len(idx) - 1):
        date = idx[t]
        if pos is not None:
            df = data[pos["sym"]]
            try:
                row = df.loc[date]
                hi, lo, cl = float(row["High"]), float(row["Low"]), float(row["Close"])
            except Exception:
                continue
            held = t - pos["t"]
            ex = None
            if lo <= pos["stop"]:          ex = ("stop", pos["stop"])
            elif hi >= pos["target1"]:     ex = ("hedef", pos["target1"])
            elif held >= max_hold:         ex = ("zaman", cl)
            if ex:
                reason, px = ex
                q = pos["qty"]
                pnl_tl = (px - pos["entry"]) * q - (px + pos["entry"]) * q * comm
                trades.append({"sym": pos["sym"], "entry_date": pos["date"], "exit_date": date,
                               "reason": reason, "pnl_tl": pnl_tl,
                               "pnl_pct": (px / pos["entry"] - 1) * 100 - comm * 200,
                               "used": q * pos["entry"]})
                if pnl_tl < 0:
                    cooldown[pos["sym"]] = date
                pos = None
            continue

        xu_sl = xu.loc[:date]
        try:
            regime, _ = advisor._market_regime(xu_sl)
        except Exception:
            regime = "RISK_ON"
        if regime == "RISK_OFF":
            continue

        all_ret = {"r5": {}, "r20": {}, "r60": {}}
        slices = {}
        for s in syms:
            df = data.get(s)
            if df is None:
                continue
            sl = df.loc[:date]
            if len(sl) < warmup or sl.index[-1] != date:
                continue
            slices[s] = sl
            c = sl["Close"]
            for k, n in (("r5", 6), ("r20", 21), ("r60", 61)):
                all_ret[k][s] = (float(c.iloc[-1]) / float(c.iloc[-n]) - 1) * 100 if len(c) > n - 1 else None
        backtest._BT_SLICES.clear(); backtest._BT_SLICES.update(slices)

        scores = []
        for s, sl in slices.items():
            try:
                scores.append(advisor.score_stock(s, sl, xu_sl, all_ret, sectors))
            except Exception:
                continue
        cd = {s for s, d in cooldown.items() if (date - d).days <= 7}
        elig = [x for x in scores
                if x["timeframe"] != "ÖNERİLMEZ" and x.get("entry_score", 0) >= entry_min
                and x.get("bb_pos", 0.5) < bb_max and x.get("rsi", 50) < rsi_max
                and x.get("rr_ratio", 0) >= rr_min and x["symbol"] not in cd]
        if not elig:
            continue
        elig.sort(key=lambda x: (x.get("entry_score", 0), x["total_score"]), reverse=True)
        b = elig[0]
        entry = float(slices[b["symbol"]]["Close"].iloc[-1])
        stop, hard = b["stop_loss"], b.get("hard_stop") or b["stop_loss"]
        if not (0 < stop < entry):
            continue
        # canlı advisor ile aynı dozlama
        rr, es = b.get("rr_ratio", 1.0) or 1.0, b.get("entry_score", 0) or 0
        conv = 1.0 if (rr >= 1.8 and es >= 5.5) else 0.85 if (rr >= 1.4 and es >= 4.5) \
            else 0.70 if (rr >= 1.2 and es >= 4.0) else 0.55
        factor = min(0.5 if regime == "CAUTION" else 1.0, conv)
        qty = CAPITAL * factor / (entry * (1 + comm))
        qty = min(qty, RISK_TL / (entry - stop))
        if hard < entry:
            qty = min(qty, MAX_LOSS / (entry - hard))
        if qty <= 0:
            continue
        pos = {"sym": b["symbol"], "entry": entry, "t": t, "date": date,
               "stop": stop, "target1": b["target1"], "qty": qty}
    return trades, idx[warmup], idx[-1]


def report(name, trades, d0, d1):
    months = max(1e-9, (d1 - d0).days / 30.44)
    print(f"\n━━━━━━━━━━ {name} ({d0.date()} → {d1.date()}, {months:.1f} ay) ━━━━━━━━━━")
    if not trades:
        print("İşlem yok."); return {}
    p = np.array([t["pnl_tl"] for t in trades])
    w, l = p[p > 0], p[p <= 0]
    eq = np.cumsum(p); dd = float(np.max(np.maximum.accumulate(eq) - eq)) if len(eq) else 0
    df = pd.DataFrame({"m": [pd.Timestamp(t["exit_date"]).strftime("%Y-%m") for t in trades], "p": p})
    bym = df.groupby("m")["p"].sum()
    reasons = pd.Series([t["reason"] for t in trades]).value_counts().to_dict()
    res = {"n": len(p), "wr": len(w) / len(p) * 100, "pf": w.sum() / abs(l.sum()) if l.sum() else 99,
           "total": p.sum(), "per_month": p.sum() / months, "dd": dd,
           "worst": p.min(), "best": p.max(), "avg_used": np.mean([t["used"] for t in trades]),
           "neg_months": int((bym < 0).sum()), "n_months": len(bym),
           "best_m": bym.max(), "worst_m": bym.min(), "trades_pm": len(p) / months}
    print(f"İşlem            : {res['n']}  (ayda ~{res['trades_pm']:.1f})")
    print(f"İsabet           : %{res['wr']:.0f}   K/Z oranı (PF): {res['pf']:.2f}")
    print(f"Toplam K/Z       : {res['total']:+,.0f} TL   → ayda ortalama {res['per_month']:+,.0f} TL")
    print(f"Ort. pozisyon    : {res['avg_used']:,.0f} TL (50 binin %{res['avg_used']/CAPITAL*100:.0f}'i)")
    print(f"En iyi / kötü    : {res['best']:+,.0f} / {res['worst']:+,.0f} TL")
    print(f"En kötü düşüş    : -{res['dd']:,.0f} TL (zirveden)")
    print(f"Aylar            : {res['n_months']} aydan {res['neg_months']}'i zararda | "
          f"en iyi ay {res['best_m']:+,.0f}, en kötü ay {res['worst_m']:+,.0f} TL")
    print(f"Çıkışlar         : {reasons}")
    return res


if __name__ == "__main__":
    print("[*] BIST verisi indiriliyor...")
    d, s, sec, c = load_bist()
    rb = report("BIST", *simulate(d, s, sec, c))
    print("\n[*] Kripto verisi indiriliyor...")
    d, s, sec, c = load_crypto()
    print(f"[*] {len(s)} coin hazır.")
    rc = report("KRİPTO", *simulate(d, s, sec, c))
