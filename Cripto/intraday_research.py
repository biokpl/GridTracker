"""
intraday_research.py — Gün içi (vur-kaç) kripto stratejileri, gerçekçi maliyetle.

Kurallar (geleceği görmemek için):
  • Sinyal i. mumun KAPANIŞIYLA, giriş (i+1). mumun AÇILIŞINDA.
  • Stop/hedef ATR ile girişte sabitlenir. Aynı mumda ikisi de görülürse
    önce STOP varsayılır (kötümser). Mum stop altında açılırsa açılıştan çıkılır.
  • Sinyal-çıkışları kapanışta tetiklenir, bir sonraki açılışta uygulanır.
  • Maliyet: her yön için COST (komisyon + kayma). Ana senaryo %0.15/yön,
    iyimser senaryo %0.10/yön.
  • Sermaye coinlere eşit bölünür (6 kova), her kova tek pozisyon.
  • EĞİTİM döneminde ayar seçilir (Sharpe), TEST döneminde ölçülür.
Kullanım: python intraday_research.py 1h   |   python intraday_research.py 15m
"""
import sys, itertools
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = Path(__file__).parent
TF = sys.argv[1] if len(sys.argv) > 1 else "1h"
DATA = pd.read_pickle(BASE / f"intraday_{TF}.pkl")
TRAIN_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
TEST_START = pd.Timestamp("2024-07-01", tz="UTC")
COSTS = {"gerçekçi %0.15/yön": 0.0015, "iyimser %0.10/yön": 0.0010}


def ema(x, n): return pd.Series(x).ewm(span=n, adjust=False, min_periods=n).mean().to_numpy()


def prep(df):
    o, h, l, c, v = (df[k].to_numpy() for k in ("o", "h", "l", "c", "v"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr = pd.Series(tr).ewm(alpha=1/14, adjust=False).mean().to_numpy()
    d = np.diff(c, prepend=c[0])
    def _rsi(n):
        up = pd.Series(np.clip(d, 0, None)).ewm(alpha=1/n, adjust=False).mean()
        dn = pd.Series(np.clip(-d, 0, None)).ewm(alpha=1/n, adjust=False).mean()
        return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50).to_numpy()
    tp = (h + l + c) / 3
    pv = pd.Series(tp * v).rolling(24).sum(); vv = pd.Series(v).rolling(24).sum()
    vwap = (pv / vv).to_numpy()
    sd = pd.Series(c).rolling(24).std().to_numpy()
    return {"o": o, "h": h, "l": l, "c": c, "atr": atr, "ema200": ema(c, 200),
            "rsi2": _rsi(2), "vwap": vwap, "sd": sd, "idx": df.index,
            "hh": {n: pd.Series(h).rolling(n).max().shift(1).to_numpy() for n in (12, 24, 48)},
            "ema": {n: ema(c, n) for n in (9, 12, 20, 21, 26, 50)}}


P = {k: prep(v) for k, v in DATA.items()}


# ── giriş sinyalleri (bool dizi) + sinyal-çıkışı (bool dizi veya None) ────────
def signals(p, strat, prm):
    c = p["c"]; trend = c > p["ema200"]
    if strat == "Kırılım":
        n, k, m, tf = prm
        ent = (c > p["hh"][n]) & (trend if tf else True)
        return ent, None
    if strat == "RSI(2) dönüş":
        thr, k, H = prm
        ent = (p["rsi2"] < thr) & trend
        return ent, p["rsi2"] > 70
    if strat == "VWAP dönüş":
        zt, k, tf = prm
        z = (c - p["vwap"]) / p["sd"]
        ent = (z < -zt) & (trend if tf else True)
        return ent, c >= p["vwap"]
    if strat == "EMA kesişim":
        (f, s), k = prm
        ef, es = p["ema"][f], p["ema"][s]
        up = (ef > es) & (np.r_[False, (ef <= es)[:-1]])
        return up & trend, ef < es
    raise ValueError(strat)


def stop_target(strat, prm):
    """(stop ATR katı, hedef ATR katı veya None, max tutma mum)"""
    if strat == "Kırılım":      n, k, m, tf = prm; return k, m, 24
    if strat == "RSI(2) dönüş": thr, k, H = prm;   return k, None, H
    if strat == "VWAP dönüş":   zt, k, tf = prm;   return k, None, 24
    if strat == "EMA kesişim":  _, k = prm;        return k, None, 48


def simulate(p, strat, prm, cost):
    ent, sx = signals(p, strat, prm)
    ks, km, H = stop_target(strat, prm)
    o, h, l, c, atr = p["o"], p["h"], p["l"], p["c"], p["atr"]
    ent = np.nan_to_num(ent.astype(float)).astype(bool)
    ent[:200] = False
    cand = np.flatnonzero(ent)
    trades = []; i_free = 0; N = len(c)
    for i in cand:
        if i < i_free or i + 1 >= N:
            continue
        e = i + 1; px = o[e]
        stop = px - ks * atr[i]; tgt = px + km * atr[i] if km else None
        x, xpx = None, None
        for j in range(e, min(N, e + H)):
            if o[j] <= stop and j > e:          xpx = o[j]; x = j; break   # boşlukla stop altı
            if l[j] <= stop:                    xpx = stop; x = j; break
            if tgt is not None:
                if j > e and o[j] >= tgt:       xpx = o[j]; x = j; break
                if h[j] >= tgt:                 xpx = tgt; x = j; break
            if sx is not None and sx[j] and j + 1 < N:
                xpx = o[j + 1]; x = j + 1; break
        if x is None:
            x = min(N - 1, e + H - 1); xpx = c[x]
        r = (xpx * (1 - cost)) / (px * (1 + cost)) - 1
        trades.append((p["idx"][x], r, x - e + 1))
        i_free = x + 1
    return trades


def portfolio(trade_lists, a, b):
    """Kovalar: her coin 1/n sermaye. Günlük getiri ≈ o gün kapanan işlemlerin ortalaması."""
    n = len(trade_lists); rows = []
    for tl in trade_lists:
        for t, r, hold in tl:
            if a <= t <= b:
                rows.append((t.normalize(), r / n, hold))
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["d", "r", "hold"])
    days = pd.date_range(a.normalize(), b.normalize(), freq="D", tz="UTC")
    daily = df.groupby("d")["r"].sum().reindex(days, fill_value=0.0)
    eq = (1 + daily).cumprod()
    m = (1 + daily).resample("ME").prod() - 1
    nt = len(df); per_trade = df["r"] * n
    return {"sharpe": daily.mean() / daily.std() * np.sqrt(365) if daily.std() > 0 else 0,
            "total": eq.iloc[-1] - 1, "dd": (eq / eq.cummax() - 1).min(),
            "months": len(m), "pos_m": (m > 0).mean(), "worst_m": m.min(),
            "trades_pm": nt / max(1, len(m)), "wr": (per_trade > 0).mean(),
            "avg": per_trade.mean(), "hold": df["hold"].mean()}


GRIDS = {
    "Kırılım":      list(itertools.product((12, 24, 48), (1.0, 2.0), (2.0, 3.0), (True, False))),
    "RSI(2) dönüş": list(itertools.product((5, 10, 15), (1.5, 3.0), (12, 24))),
    "VWAP dönüş":   list(itertools.product((1.5, 2.0, 2.5), (1.5, 3.0), (True, False))),
    "EMA kesişim":  list(itertools.product(((9, 21), (12, 26), (20, 50)), (2.0, 3.0))),
}


def main():
    t_end = min(v["idx"][-1] for v in P.values())
    t0 = max(v["idx"][200] for v in P.values())
    print(f"[{TF}] {len(P)} coin, {t0.date()} → {t_end.date()} | eğitim → {TRAIN_END.date()}, test {TEST_START.date()} →\n")
    for cname, cost in COSTS.items():
        print("═" * 118)
        print(f"MALİYET: {cname}  (gidiş-dönüş ≈ %{cost*200:.1f})")
        print(f"{'strateji':14s} {'seçilen ayar':26s} │ {'eğt.Sharpe':>10s} │ {'TEST toplam':>11s} {'düşüş':>6s} {'Sharpe':>6s} "
              f"{'+ay':>4s} {'işlem/ay':>8s} {'isabet':>6s} {'ort.işlem':>9s} {'ort.süre':>8s}")
        print("─" * 118)
        for strat, grid in GRIDS.items():
            best = None
            for prm in grid:
                tls = [simulate(p, strat, prm, cost) for p in P.values()]
                tr = portfolio(tls, t0, TRAIN_END)
                if tr and (best is None or tr["sharpe"] > best[1]["sharpe"]):
                    best = (prm, tr, tls)
            prm, tr, tls = best
            te = portfolio(tls, TEST_START, t_end)
            print(f"{strat:14s} {str(prm):26s} │ {tr['sharpe']:10.2f} │ {te['total']*100:+10.0f}% {te['dd']*100:5.0f}% "
                  f"{te['sharpe']:6.2f} {te['pos_m']*100:3.0f}% {te['trades_pm']:8.0f} {te['wr']*100:5.0f}% "
                  f"{te['avg']*100:+8.2f}% {te['hold']:6.1f} mum")
        print()


if __name__ == "__main__":
    main()
