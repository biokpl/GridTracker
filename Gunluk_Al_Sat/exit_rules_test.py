"""
exit_rules_test.py — ÇIKIŞ KURALLARI karşılaştırması (2026-10-23).

Soru: Stop'a gelip birkaç gün sonra dönen hisselerde dar stopla "boşuna" zarar
mı ediyoruz? Geniş stop + küçük lot, kapanış onaylı stop, planlı takviye,
stopsuz bekleme... hangisi gerçekten daha iyi?

Adil karşılaştırma:
  • GİRİŞLER ortak: advisor.score_stock (canlı sistemle aynı çekirdek) her gün
    #1 adayı seçer. Seçimler bir kez hesaplanır (picks cache), tüm varyantlar
    aynı aday listesini tek-pozisyon rotasyonuyla kullanır.
  • LOT risk bazlı: plandaki en kötü çıkışta zarar = RISK_TL (1.500 TL),
    pozisyon maliyeti ≤ SERMAYE (50.000 TL). RISK_OFF günlerinde yarım lot
    (config regime_mode="half" ile aynı).
  • Sonuç TL: toplam net K/Z, isabet, PF, en kötü işlem, en büyük dönem kaybı.

Kullanım: python exit_rules_test.py           (5 yıl)
          python exit_rules_test.py --years 3
"""
import sys, json, pickle, argparse, time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
import backtest as bt          # yamalar (weekly_trend, event_risk) burada uygulanıyor
import advisor

CFG = bt.CFG
SYMBOLS, SECTORS, COMM = bt.SYMBOLS, bt.SECTORS, bt.COMM
CAPITAL = 50_000.0
RISK_TL = 1_500.0


# ── veri ─────────────────────────────────────────────────────────────────────
def download(years):
    cache = BASE / f"_ert_data_{years}y.pkl"
    if cache.exists() and time.time() - cache.stat().st_mtime < 12 * 3600:
        return pickle.loads(cache.read_bytes())
    print(f"[ERT] {len(SYMBOLS)} sembol + XU100, {years} yıl indiriliyor...")
    tickers = [f"{s}.IS" for s in SYMBOLS] + ["XU100.IS"]
    raw = yf.download(tickers, period=f"{years}y", interval="1d",
                      auto_adjust=True, progress=False, threads=True)
    data = {}
    for s in SYMBOLS + ["XU100"]:
        try:
            df = raw.xs(f"{s}.IS", axis=1, level=1).dropna(how="all")
            if len(df) >= 80:
                data[s] = df
        except Exception:
            pass
    common = data["XU100"].index
    for s in data:
        if s != "XU100":
            common = common.union(data[s].index)
    for s in list(data):
        data[s] = data[s].reindex(common).ffill()
    cache.write_bytes(pickle.dumps(data))
    print(f"[ERT] {len(data) - 1} sembol hazır.")
    return data


def atr14(df):
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(14, min_periods=10).mean()


# ── günlük #1 aday (canlı filtrelerle) ───────────────────────────────────────
def build_picks(data, years, bb_max=0.70, rsi_max=70.0, rr_min=1.0, entry_min=3.0):
    cache = BASE / f"_ert_picks_{years}y.pkl"
    if cache.exists() and time.time() - cache.stat().st_mtime < 12 * 3600:
        return pickle.loads(cache.read_bytes())
    xu = data["XU100"]; idx = xu.index; N = len(idx); warm = 65
    atrs = {s: atr14(df) for s, df in data.items() if s != "XU100"}
    picks = {}
    t0 = time.time()
    for t in range(warm, N - 1):
        xu_sl = xu.iloc[:t + 1]
        try:
            regime, _ = advisor._market_regime(xu_sl)
        except Exception:
            regime = "RISK_ON"
        all_ret = {"r5": {}, "r20": {}, "r60": {}}; slices = {}
        for s in SYMBOLS:
            df = data.get(s)
            if df is None:
                continue
            sl = df.iloc[:t + 1]
            if sl["Close"].notna().sum() < warm:
                continue
            slices[s] = sl
            c = sl["Close"]
            for k, n in (("r5", 6), ("r20", 21), ("r60", 61)):
                all_ret[k][s] = (float(c.iloc[-1]) / float(c.iloc[-n]) - 1) * 100 if len(c) >= n else None
        bt._BT_SLICES.clear(); bt._BT_SLICES.update(slices)
        scores = []
        for s, sl in slices.items():
            try:
                scores.append(advisor.score_stock(s, sl, xu_sl, all_ret, SECTORS))
            except Exception:
                pass
        el = [x for x in scores if x["timeframe"] != "ÖNERİLMEZ"
              and x.get("entry_score", 0) >= entry_min and x.get("bb_pos", .5) < bb_max
              and x.get("rsi", 50) < rsi_max and x.get("rr_ratio", 0) >= rr_min]
        el.sort(key=lambda x: (x.get("entry_score", 0), x["total_score"]), reverse=True)
        if el:
            b = el[0]; s = b["symbol"]
            picks[t] = dict(sym=s, entry=float(data[s]["Close"].iloc[t]), stop=float(b["stop_loss"]),
                            hard=float(b.get("hard_stop") or b["stop_loss"]), target=float(b["target1"]),
                            atr=float(atrs[s].iloc[t]), regime=regime)
        if (t - warm) % 50 == 0:
            el_t = time.time() - t0; done = t - warm + 1; tot = N - 1 - warm
            print(f"[ERT] gün {done}/{tot}  ~{el_t / done * (tot - done) / 60:.1f} dk kaldı", flush=True)
    cache.write_bytes(pickle.dumps(picks))
    return picks


# ── çıkış kuralları ──────────────────────────────────────────────────────────
# Her kural: plan(pick) → dict(stop, hard, target, max_hold, close_stop, adds)
#   stop      : gün içi Low değerse çıkış (close_stop=False) / kapanış altındaysa (True)
#   hard      : close_stop modunda gün içi felaket seviyesi (Low değerse anında)
#   adds      : planlı takviyeler [(fiyat, oran)] — giriş lotunun oranı kadar ekle
#   risk_px   : lot hesabındaki "en kötü çıkış" fiyatı (tüm takviyeler dolmuş varsayımıyla)
def R_current(p):
    return dict(stop=p["stop"], target=p["target"], max_hold=5)

def R_atr(k, hold=5, tgt_k=None):
    def f(p):
        st = p["entry"] - k * p["atr"]
        tg = p["entry"] + tgt_k * k * p["atr"] if tgt_k else p["target"]
        return dict(stop=st, target=tg, max_hold=hold)
    return f

def R_close(k_soft=1.0, k_hard=2.5, hold=5):
    def f(p):
        return dict(stop=p["entry"] - k_soft * p["atr"], hard=p["entry"] - k_hard * p["atr"],
                    target=p["target"], max_hold=hold, close_stop=True)
    return f

def R_scale(add_k=1.0, stop_k=2.0, hold=7):
    """Yarım lotla gir, entry−add_k·ATR'de diğer yarıyı ekle; stop entry−stop_k·ATR."""
    def f(p):
        return dict(stop=p["entry"] - stop_k * p["atr"], target=p["target"], max_hold=hold,
                    first=0.5, adds=[(p["entry"] - add_k * p["atr"], 0.5)])
    return f

def R_nostop(hold):
    def f(p):
        return dict(stop=None, target=p["target"], max_hold=hold, size_by="capital")
    return f

def R_average_down(hold=20):
    """Kullanıcının TUPRS akışı: tam lot gir, −%2 ve −%4'te tam lot daha ekle, stop yok."""
    def f(p):
        e = p["entry"]
        return dict(stop=None, target=p["target"], max_hold=hold, size_by="capital_third",
                    first=1.0, adds=[(e * 0.98, 1.0), (e * 0.96, 1.0)])
    return f


def simulate(data, picks, rule, half_in_risk_off=True):
    idx = data["XU100"].index; N = len(idx)
    trades = []; pos = None; equity = 0.0; peak_eq = 0.0; max_dd = 0.0
    t = min(picks) if picks else N
    while t < N - 1:
        if pos is None:
            p = picks.get(t)
            if p is None or not np.isfinite(p["atr"]) or p["atr"] <= 0:
                t += 1; continue
            plan = rule(p)
            e = p["entry"]
            first = plan.get("first", 1.0)
            adds = plan.get("adds", [])
            mult = 0.5 if (half_in_risk_off and p["regime"] == "RISK_OFF") else 1.0
            sb = plan.get("size_by")
            if sb == "capital":
                unit = CAPITAL / e
            elif sb == "capital_third":
                unit = CAPITAL / 3 / e
            else:
                # risk bazlı: tüm takviyeler dolmuş + en kötü çıkış = RISK_TL
                worst = plan.get("hard") or plan["stop"]
                fills = [(e, first)] + [(px, r) for px, r in adds]
                loss_per_unit = sum(r * (px - worst) for px, r in fills)
                if worst is None or loss_per_unit <= 0:
                    t += 1; continue
                unit = RISK_TL / loss_per_unit
                cost_per_unit = sum(r * px for px, r in fills)
                unit = min(unit, CAPITAL / cost_per_unit)
            unit *= mult
            pos = dict(sym=p["sym"], t0=t, plan=plan, lots=[(e, unit * first)],
                       pending=[(px, unit * r) for px, r in adds], entry0=e)
            t += 1; continue

        df = data[pos["sym"]]
        hi, lo, cl = (float(df[c].iloc[t]) for c in ("High", "Low", "Close"))
        plan = pos["plan"]; held = t - pos["t0"]
        # planlı takviyeler (gün içi o fiyata değdiyse dolar)
        still = []
        for px, q in pos["pending"]:
            if lo <= px:
                pos["lots"].append((px, q))
            else:
                still.append((px, q))
        pos["pending"] = still
        ex = None
        st, hard = plan.get("stop"), plan.get("hard")
        if plan.get("close_stop"):
            if hard is not None and lo <= hard: ex = ("felaket", hard)
            elif st is not None and cl <= st:  ex = ("stop-kapanış", cl)
        elif st is not None and lo <= st:
            ex = ("stop", st)
        if ex is None and hi >= plan["target"]: ex = ("hedef", plan["target"])
        if ex is None and held >= plan["max_hold"]: ex = ("zaman", cl)
        if ex:
            reason, xpx = ex
            qty = sum(q for _, q in pos["lots"])
            cost = sum(px * q for px, q in pos["lots"])
            pnl = xpx * qty - cost - COMM * (cost + xpx * qty)
            trades.append(dict(sym=pos["sym"], date=str(idx[pos["t0"]].date()), held=held,
                               reason=reason, pnl=pnl, cost=cost,
                               adds=len(pos["lots"]) - 1))
            equity += pnl; peak_eq = max(peak_eq, equity); max_dd = max(max_dd, peak_eq - equity)
            pos = None
        t += 1
    return trades, max_dd


def summarize(name, trades, max_dd, years):
    if not trades:
        return dict(name=name, n=0)
    p = np.array([x["pnl"] for x in trades])
    w, l = p[p > 0], p[p <= 0]
    reasons = {}
    for x in trades: reasons[x["reason"]] = reasons.get(x["reason"], 0) + 1
    return dict(name=name, n=len(p), wr=len(w) / len(p) * 100, total=p.sum(),
                per_month=p.sum() / (years * 12), pf=w.sum() / abs(l.sum()) if l.sum() else 99,
                avg_w=w.mean() if len(w) else 0, avg_l=l.mean() if len(l) else 0,
                worst=p.min(), best=p.max(), max_dd=max_dd,
                hold=np.mean([x["held"] for x in trades]), reasons=reasons)


RULES = [
    ("A  Şu anki (dar stop ~%1, 5 gün)",         R_current),
    ("B1 ATR 1.5x stop + küçük lot",              R_atr(1.5)),
    ("B2 ATR 2x stop + küçük lot",                R_atr(2.0)),
    ("B3 ATR 2.5x stop + küçük lot",              R_atr(2.5)),
    ("B4 ATR 2x stop, 10 gün",                    R_atr(2.0, hold=10)),
    ("B5 ATR 2x stop, hedef 1.5R, 10 gün",        R_atr(2.0, hold=10, tgt_k=1.5)),
    ("C1 Kapanış onaylı (1 ATR) + felaket 2.5 ATR", R_close(1.0, 2.5)),
    ("C2 Kapanış onaylı (1.5 ATR) + felaket 3 ATR", R_close(1.5, 3.0, hold=7)),
    ("D  Planlı takviye (yarım+yarım, 2 ATR stop)", R_scale(1.0, 2.0, 7)),
    ("E1 Stopsuz, 5 gün (tam sermaye)",           R_nostop(5)),
    ("E2 Stopsuz, 20 gün (tam sermaye)",          R_nostop(20)),
    ("F  Düşüşte 2 takviye, stopsuz, 20 gün",     R_average_down(20)),
]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--years", type=int, default=5)
    a = ap.parse_args()
    data = download(a.years)
    picks = build_picks(data, a.years)
    days = len(data["XU100"].index)
    yrs = days / 252
    print(f"\n[ERT] {len(picks)} günde aday var, veri {days} gün (~{yrs:.1f} yıl)\n")
    rows = []
    for name, rule in RULES:
        tr, dd = simulate(data, picks, rule)
        rows.append(summarize(name, tr, dd, yrs))
    hdr = f"{'Kural':46s} {'İşlem':>5s} {'İsabet':>6s} {'PF':>5s} {'Toplam TL':>11s} {'Aylık':>8s} {'Ort+':>7s} {'Ort−':>8s} {'EnKötü':>8s} {'MaxDD':>8s} {'Gün':>4s}"
    print(hdr); print("-" * len(hdr))
    for r in rows:
        if not r["n"]:
            print(f"{r['name']:46s} işlem yok"); continue
        print(f"{r['name']:46s} {r['n']:5d} {r['wr']:5.1f}% {r['pf']:5.2f} {r['total']:11,.0f} {r['per_month']:8,.0f} "
              f"{r['avg_w']:7,.0f} {r['avg_l']:8,.0f} {r['worst']:8,.0f} {r['max_dd']:8,.0f} {r['hold']:4.1f}")
    print()
    for r in rows:
        if r["n"]:
            print(f"{r['name'][:3]} çıkışlar: {r['reasons']}")
    out = BASE / "exit_rules_result.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"\n[ERT] sonuç: {out}")


if __name__ == "__main__":
    main()
