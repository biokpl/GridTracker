"""
strategy_research.py — 2-3 günlük "vur-kaç" için EN İYİ giriş+çıkış kombinasyonu (2026-10-23).

Yöntem (aşırı uyumu önlemek için):
  • Her gün advisor.score_stock ile TÜM BIST100 puanlanır; ilk 15 aday tüm
    özellikleriyle kaydedilir (cands cache).
  • EĞİTİM = ilk %60 günler: filtre × sıralama × giriş zamanı × çıkış ızgarası taranır.
  • DOĞRULAMA = son %40 günler: eğitimde seçilen en iyi birkaç kombinasyon
    hiç görmediği veride ölçülür. Rapor her ikisini de verir.
  • Pozisyon: tek pozisyon, 50.000 TL (RISK_OFF'ta yarım), komisyon gidiş-dönüş,
    boşluklu açılışta stop açılıştan dolar, aynı gün hem stop hem hedef → stop sayılır.

Kullanım: python strategy_research.py
"""
import sys, json, pickle, time, itertools
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
import exit_rules_test as E
import backtest as bt
import advisor

CAPITAL = 50_000.0
COMM = E.COMM
TOPN = 15
TRAIN_FRAC = 0.60


def build_cands(data, years=5):
    cache = BASE / f"_sr_cands_{years}y.pkl"
    if cache.exists() and time.time() - cache.stat().st_mtime < 24 * 3600:
        return pickle.loads(cache.read_bytes())
    xu = data["XU100"]; idx = xu.index; N = len(idx); warm = 65
    atrs = {s: E.atr14(df) for s, df in data.items() if s != "XU100"}
    out = {}; t0 = time.time()
    for t in range(warm, N - 1):
        xu_sl = xu.iloc[:t + 1]
        try:
            regime, _ = advisor._market_regime(xu_sl)
        except Exception:
            regime = "RISK_ON"
        all_ret = {"r5": {}, "r20": {}, "r60": {}}; slices = {}
        for s in E.SYMBOLS:
            df = data.get(s)
            if df is None:
                continue
            sl = df.iloc[:t + 1]
            if sl["Close"].notna().sum() < warm:
                continue
            slices[s] = sl; c = sl["Close"]
            for k, n in (("r5", 6), ("r20", 21), ("r60", 61)):
                all_ret[k][s] = (float(c.iloc[-1]) / float(c.iloc[-n]) - 1) * 100 if len(c) >= n else None
        bt._BT_SLICES.clear(); bt._BT_SLICES.update(slices)
        sc = []
        for s, sl in slices.items():
            try:
                x = advisor.score_stock(s, sl, xu_sl, all_ret, E.SECTORS)
            except Exception:
                continue
            if x["timeframe"] == "ÖNERİLMEZ":
                continue
            sc.append(x)
        sc.sort(key=lambda x: (x.get("entry_score", 0), x["total_score"]), reverse=True)
        day = []
        for x in sc[:TOPN]:
            s = x["symbol"]
            d = {k: x.get(k) for k in ("symbol", "total_score", "entry_score", "rr_ratio", "rsi", "bb_pos",
                                       "atr_pct", "beta", "mdd_60", "vol_ratio", "r5", "r20", "r60",
                                       "stop_loss", "target1")}
            d.update({f"s_{k}": v for k, v in (x.get("scores") or {}).items()})
            d["close"] = float(data[s]["Close"].iloc[t]); d["atr"] = float(atrs[s].iloc[t])
            day.append(d)
        out[t] = dict(regime=regime, cands=day)
        if (t - warm) % 100 == 0:
            done = t - warm + 1; tot = N - 1 - warm
            print(f"[SR] gün {done}/{tot} ~{(time.time() - t0) / done * (tot - done) / 60:.1f} dk", flush=True)
    cache.write_bytes(pickle.dumps(out))
    return out


# ── simülasyon ───────────────────────────────────────────────────────────────
_ARR = {}

def _arr(data, s):
    a = _ARR.get(s)
    if a is None:
        df = data[s]; a = _ARR[s] = {k: df[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close")}
    return a


def simulate(data, cands, days, filt, rank, exit_, entry_mode="close", only_risk_on=False):
    """filt(c)->bool, rank(c)->sıralama, exit_=(stop%|None, hedef%, gün).
    close: t kapanışında gir, t+1'den itibaren yönet. open: t+1 açılışında gir, aynı gün yönet.
    Aynı gün stop+hedef → stop (temkinli). Boşluklu açılış: stop/hedef açılıştan dolar."""
    st_p, tg_p, hold = exit_
    N = len(data["XU100"].index)
    tr = []; pos = None; eq = pk = dd = 0.0
    dset = set(days); t = days[0]; tmax = days[-1]
    while t <= tmax and t < N - 1:
        if pos is None:
            day = cands.get(t)
            if t in dset and day and not (only_risk_on and day["regime"] == "RISK_OFF"):
                el = [c for c in day["cands"] if filt(c)]
                if el:
                    c = max(el, key=rank); a = _arr(data, c["symbol"])
                    t_in = t if entry_mode == "close" else t + 1
                    e = c["close"] if entry_mode == "close" else a["Open"][t + 1]
                    if np.isfinite(e) and e > 0:
                        q = CAPITAL * (0.5 if day["regime"] == "RISK_OFF" else 1.0) / e
                        pos = dict(a=a, e=e, q=q, t0=t_in, sym=c["symbol"],
                                   stop=e * (1 - st_p / 100) if st_p else None, tgt=e * (1 + tg_p / 100))
            t += 1
            if pos is not None and entry_mode == "open":
                pass                      # t artık t_in (= t+1): aynı gün yönetilecek
            continue
        a = pos["a"]; op, hi, lo, cl = a["Open"][t], a["High"][t], a["Low"][t], a["Close"][t]
        held = t - pos["t0"]; gap = held > 0; ex = None
        if not np.isfinite(cl):
            t += 1; continue
        if pos["stop"] is not None and lo <= pos["stop"]:
            ex = min(pos["stop"], op) if gap else pos["stop"]
        elif hi >= pos["tgt"]:
            ex = max(pos["tgt"], op) if gap else pos["tgt"]
        elif held >= hold:
            ex = cl
        if ex is not None:
            pnl = (ex - pos["e"]) * pos["q"] - COMM * (ex + pos["e"]) * pos["q"]
            tr.append(dict(pnl=pnl, held=held, sym=pos["sym"], t=pos["t0"]))
            eq += pnl; pk = max(pk, eq); dd = max(dd, pk - eq); pos = None
        t += 1
    return tr, dd


def stats(tr, dd, ndays):
    if len(tr) < 20:
        return None
    p = np.array([x["pnl"] for x in tr]); months = ndays / 21
    w, l = p[p > 0], p[p <= 0]
    return dict(n=len(p), wr=(p > 0).mean() * 100, avg=p.mean(), month=p.sum() / months,
                pf=w.sum() / abs(l.sum()) if l.sum() else 99, dd=dd, worst=p.min(),
                hold=np.mean([x["held"] for x in tr]), per_month_n=len(p) / months)


# ── arama uzayı ──────────────────────────────────────────────────────────────
def g(c, k, d=0.0):
    v = c.get(k); return d if v is None else v

FILTERS = {
    "hepsi": lambda c: True,
    "canlı (bb<.70 rsi<70 rr≥1 entry≥3)": lambda c: g(c, "bb_pos", .5) < .70 and g(c, "rsi", 50) < 70 and g(c, "rr_ratio") >= 1 and g(c, "entry_score") >= 3,
    "entry≥4": lambda c: g(c, "entry_score") >= 4,
    "entry≥5": lambda c: g(c, "entry_score") >= 5,
    "total≥6": lambda c: g(c, "total_score") >= 6,
    "hacim≥1.3": lambda c: g(c, "vol_ratio", 1) >= 1.3,
    "hacim≥1.5 & r5>0": lambda c: g(c, "vol_ratio", 1) >= 1.5 and g(c, "r5") > 0,
    "rsi 40-60": lambda c: 40 <= g(c, "rsi", 50) <= 60,
    "rsi<40 (dip)": lambda c: g(c, "rsi", 50) < 40,
    "bb<0.3 (alt bant)": lambda c: g(c, "bb_pos", .5) < .3,
    "momentum: r5>0 & r20>0": lambda c: g(c, "r5") > 0 and g(c, "r20") > 0,
    "pullback: r20>5 & r5<0": lambda c: g(c, "r20") > 5 and g(c, "r5") < 0,
    "oynak: atr%≥3": lambda c: g(c, "atr_pct") >= 3,
    "sakin: atr%<2.5": lambda c: g(c, "atr_pct") < 2.5,
    "rs≥7": lambda c: g(c, "s_rel_strength") >= 7,
}
RANKS = {
    "entry": lambda c: (g(c, "entry_score"), g(c, "total_score")),
    "total": lambda c: g(c, "total_score"),
    "momentum": lambda c: g(c, "s_momentum"),
    "r5 (kısa güç)": lambda c: g(c, "r5"),
    "hacim": lambda c: g(c, "vol_ratio"),
    "oynaklık": lambda c: g(c, "atr_pct"),
    "rs": lambda c: g(c, "s_rel_strength"),
}
EXITS = [(st, tg, h) for h in (1, 2, 3) for st in (None, 1.0, 1.5, 2.0, 3.0) for tg in (1.5, 2.0, 3.0, 4.0, 5.0)]


def main():
    data = E.download(5)
    cands = build_cands(data)
    days = sorted(cands); cut = days[int(len(days) * TRAIN_FRAC)]
    train = [d for d in days if d < cut]; test = [d for d in days if d >= cut]
    idx = data["XU100"].index
    print(f"\n[SR] eğitim {idx[train[0]].date()}–{idx[train[-1]].date()} ({len(train)} gün) | "
          f"doğrulama {idx[test[0]].date()}–{idx[test[-1]].date()} ({len(test)} gün)")
    res = []; t0 = time.time()
    combos = list(itertools.product(FILTERS.items(), RANKS.items(), ("close", "open"), (False, True)))
    for i, ((fn, f), (rn, r), em, ro) in enumerate(combos):
        for ex in EXITS:
            tr, dd = simulate(data, cands, train, f, r, ex, em, ro)
            s = stats(tr, dd, len(train))
            if s:
                res.append(dict(filter=fn, rank=rn, entry=em, risk_on=ro, exit=ex, **s))
        if i % 20 == 0:
            print(f"[SR] kombinasyon {i + 1}/{len(combos)} ({time.time() - t0:.0f} sn)", flush=True)
    # eğitimde sağlam olanlar: yeterli işlem, düşük-orta DD; aylık kâra göre sırala
    ok = [r for r in res if r["n"] >= 60 and r["pf"] >= 1.2]
    ok.sort(key=lambda r: r["month"], reverse=True)
    top = ok[:40]
    for r in top:
        f, rk = FILTERS[r["filter"]], RANKS[r["rank"]]
        tr, dd = simulate(data, cands, test, f, rk, r["exit"], r["entry"], r["risk_on"])
        s = stats(tr, dd, len(test)) or {}
        r["test"] = s
    # referans: canlı sistem (canlı filtre, entry sırası, kapanış, st1/tg4/2g ve mevcut)
    ref = {}
    for name, ex in (("canlı + stop1/hedef4/2g", (1.0, 4.0, 2)),):
        for part, ds in (("eğitim", train), ("doğrulama", test)):
            tr, dd = simulate(data, cands, ds, FILTERS["canlı (bb<.70 rsi<70 rr≥1 entry≥3)"], RANKS["entry"], ex)
            ref[f"{name} | {part}"] = stats(tr, dd, len(ds))
    out = dict(train=[str(idx[train[0]].date()), str(idx[train[-1]].date())],
               test=[str(idx[test[0]].date()), str(idx[test[-1]].date())], top=top, ref=ref, n_tested=len(res))
    (BASE / "strategy_research_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("\n=== EĞİTİMDE EN İYİ 40 → DOĞRULAMA ===")
    print(f"{'filtre':36s} {'sıra':12s} {'giriş':5s} {'RO':2s} {'çıkış':16s} | {'eğt aylık':>9s} {'ort':>5s} {'PF':>4s} | {'DOĞ aylık':>9s} {'ort':>5s} {'PF':>4s} {'işlem':>5s} {'DD':>6s}")
    for r in top:
        s = r["test"]
        ex = f"st{r['exit'][0]}/tg{r['exit'][1]}/{r['exit'][2]}g"
        print(f"{r['filter'][:36]:36s} {r['rank'][:12]:12s} {r['entry']:5s} {'E' if r['risk_on'] else '-':2s} {ex:16s} | "
              f"{r['month']:9,.0f} {r['avg']:5.0f} {r['pf']:4.2f} | {s.get('month', 0):9,.0f} {s.get('avg', 0):5.0f} {s.get('pf', 0):4.2f} {s.get('n', 0):5d} {s.get('dd', 0):6,.0f}")
    print("\nREFERANS:", json.dumps(ref, ensure_ascii=False, default=lambda x: round(float(x), 1)))


if __name__ == "__main__":
    main()
