"""
improve_test.py — VK3 İYİLEŞTİRME testleri (2026-11-10).

Taban: canlı VK3 (ATR%≥3 havuzu, momentum sırası, ertesi açılış girişi, hedef %5,
stop %7, en fazla 3 gün, TAM sermaye). Her iyileştirme tek tek ve birlikte denenir:
  • rejim     : RISK_OFF günlerinde yeni alım yok
  • endeks    : XU100 kapanışı 20 günlük ortalamanın altındaysa yeni alım yok
  • tatil     : bayram/tatil arası pozisyon taşıma (tatil öncesi kapanışta sat, girme)
  • risk lot  : stopta en fazla R TL zarar edecek kadar lot
  • 2'ye böl  : sermaye ikiye bölünür, ilk 2 öneri aynı anda
  • başa baş  : +%3 görünce stop alış fiyatına çekilir
Veri: strategy_research önbelleği (_ert_data_5y.pkl, _sr_cands_5y.pkl; 2021-10 → 2026-10-22).
Doğrulama: ilk %60 (eğitim) / son %40 (doğrulama) ayrı raporlanır.
"""
import sys, pickle
from pathlib import Path
import numpy as np

BASE = Path(__file__).parent
CAPITAL = 50_000.0
COMM = 0.0004

data = pickle.loads((BASE / "_ert_data_5y.pkl").read_bytes())
C = pickle.loads((BASE / "_sr_cands_5y.pkl").read_bytes())
days = sorted(C)
idx = data["XU100"].index
N = len(idx)
xu = data["XU100"]["Close"].to_numpy(float)
sma20 = data["XU100"]["Close"].rolling(20).mean().to_numpy(float)
HOL = np.zeros(N, bool)          # t'den sonra tatil var mı (hafta sonu dışında boşluk)
for t in range(N - 1):
    gap = (idx[t + 1] - idx[t]).days
    HOL[t] = gap > (3 if idx[t].weekday() == 4 else 1)

ARR = {}
def arr(s):
    if s not in ARR:
        df = data[s]; ARR[s] = {k: df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close")}
    return ARR[s]


def pool(t):
    return sorted([c for c in C[t]["cands"] if (c.get("atr_pct") or 0) >= 3.0],
                  key=lambda c: c.get("s_momentum") or 0, reverse=True)


def sim(dset, slots=1, risk=None, regime=False, index=False, holiday=False, be=None,
        stop_p=7.0, tgt_p=5.0, hold=3, half=False, cool=False):
    tr = []; pos = []; eq = pk = dd = 0.0; exited = -1
    t = min(dset); tmax = max(dset)
    while t <= tmax and t < N - 1:
        # 1) açık pozisyonları yönet
        keep = []
        for p in pos:
            if t < p["t0"]:
                keep.append(p); continue
            a = p["a"]; op, hi, lo, cl = a["Open"][t], a["High"][t], a["Low"][t], a["Close"][t]
            held = t - p["t0"]; gap = held > 0; ex = None
            if not np.isfinite(cl):
                keep.append(p); continue
            if lo <= p["stop"]:
                ex = min(p["stop"], op) if gap else p["stop"]
            elif hi >= p["tgt"]:
                ex = max(p["tgt"], op) if gap else p["tgt"]
            elif held >= hold or (holiday and HOL[t]):
                ex = cl
            if ex is None:
                if be and hi >= p["e"] * (1 + be / 100):
                    p["stop"] = max(p["stop"], p["e"] * 1.002)
                keep.append(p); continue
            pnl = (ex - p["e"]) * p["q"] - COMM * (ex + p["e"]) * p["q"]
            tr.append(dict(pnl=pnl, t=p["t0"], sym=p["sym"]))
            eq += pnl; pk = max(pk, eq); dd = max(dd, pk - eq); exited = t
        pos = keep
        # 2) boş yer varsa t akşamı seç, t+1 açılışta gir
        if t in dset and len(pos) < slots and t + 1 < N:
            ok = True
            if regime and C[t]["regime"] == "RISK_OFF": ok = False
            if index and not (xu[t] >= sma20[t]): ok = False
            if holiday and HOL[t + 1]: ok = False
            if cool and exited == t: ok = False
            if ok:
                held_syms = {p["sym"] for p in pos}
                for c in pool(t):
                    if len(pos) >= slots: break
                    if c["symbol"] in held_syms: continue
                    a = arr(c["symbol"]); e = a["Open"][t + 1]
                    if not (np.isfinite(e) and e > 0): continue
                    q = CAPITAL / slots / e
                    if half and C[t]["regime"] == "RISK_OFF": q *= 0.5
                    if risk: q = min(q, risk / (e * stop_p / 100))
                    pos.append(dict(a=a, e=e, q=q, t0=t + 1, sym=c["symbol"],
                                    stop=e * (1 - stop_p / 100), tgt=e * (1 + tgt_p / 100)))
                    held_syms.add(c["symbol"])
        t += 1
    return tr, dd


def stats(tr, dd, nd):
    p = np.array([x["pnl"] for x in tr]); m = nd / 21
    if len(p) == 0: return None
    # en kötü 3 aylık dönem (63 işlem günü, gerçekleşen)
    by_t = {}
    for x in tr: by_t[x["t"]] = by_t.get(x["t"], 0) + x["pnl"]
    return dict(n=len(p), wr=(p > 0).mean() * 100, month=p.sum() / m, avg=p.mean(),
                pf=p[p > 0].sum() / max(1e-9, abs(p[p <= 0].sum())), worst=p.min(), dd=dd,
                losing_months=None)


VARIANTS = [
    ("0  CANLI VK3 (taban)",            {}),
    ("1  Rejim filtresi (RISK_OFF yok)", dict(regime=True)),
    ("2  Endeks filtresi (XU100<SMA20)", dict(index=True)),
    ("3  Tatil kuralı",                  dict(holiday=True)),
    ("4a Risk lot 1.500 TL",             dict(risk=1500)),
    ("4b Risk lot 2.500 TL",             dict(risk=2500)),
    ("5  Sermaye 2'ye bölünür",          dict(slots=2)),
    ("6  Başa baş stop (+%3)",           dict(be=3)),
    ("7a Stop %5",                       dict(stop_p=5.0)),
    ("7b Stop %4",                       dict(stop_p=4.0)),
]


def monthly(tr):
    m = {}
    for x in tr:
        k = (idx[x["t"]].year, idx[x["t"]].month); m[k] = m.get(k, 0) + x["pnl"]
    return m


def report(variants, label_extra=""):
    cut = days[int(len(days) * 0.6)]
    sets = {"5 YIL": days, "EĞİTİM": [d for d in days if d < cut], "DOĞRULAMA": [d for d in days if d >= cut]}
    print(f"Eğitim {idx[days[0]].date()}→{idx[cut-1].date()} | Doğrulama {idx[cut].date()}→{idx[days[-1]].date()}")
    rows = []
    for name, kw in variants:
        r = {"name": name}
        for sname, ds in sets.items():
            tr, dd = sim(set(ds), **kw); s = stats(tr, dd, len(ds))
            if sname == "5 YIL":
                mm = monthly(tr); s["neg_m"] = sum(1 for v in mm.values() if v < 0); s["tot_m"] = len(mm)
            r[sname] = s
        rows.append(r)
        a, b, c = r["5 YIL"], r["EĞİTİM"], r["DOĞRULAMA"]
        print(f"{name:34s} | 5y: {a['n']:3d} işl %{a['wr']:2.0f} isabet aylık {a['month']:6,.0f} PF {a['pf']:.2f} "
              f"en kötü {a['worst']:7,.0f} DD {a['dd']:7,.0f} eksi ay {a['neg_m']}/{a['tot_m']} | "
              f"eğt {b['month']:6,.0f} | doğ {c['month']:6,.0f} PF {c['pf']:.2f} DD {c['dd']:6,.0f}")
    return rows


if __name__ == "__main__":
    print("=== TEK TEK ===")
    report(VARIANTS)


# ── SAĞLAM ölçüm: başlangıç günü kaydırılarak (yol bağımlılığı / şans etkisini ayıklar) ──
COMBOS = [
    ("8  Endeks + başa baş",               dict(index=True, be=3)),
    ("9  Endeks + başa baş + tatil",       dict(index=True, be=3, holiday=True)),
    ("10 Endeks + başa baş + 2'ye böl",    dict(index=True, be=3, slots=2)),
    ("11 Endeks + başa baş + risk 2.500",  dict(index=True, be=3, risk=2500)),
]


def robust(variants, offsets=8):
    cut = days[int(len(days) * 0.6)]
    full = days; val = [d for d in days if d >= cut]
    print(f"Her satır: {offsets} farklı başlangıç gününün ORTALAMASI (aralık: en kötü…en iyi)")
    out = []
    for name, kw in variants:
        R = {}
        for sname, ds in (("5y", full), ("doğ", val)):
            ms, dds, wrs, worst, neg = [], [], [], [], []
            for k in range(offsets):
                sub = ds[k:]; tr, dd = sim(set(sub), **kw); s = stats(tr, dd, len(sub))
                ms.append(s["month"]); dds.append(dd); wrs.append(s["wr"]); worst.append(s["worst"])
                mm = monthly(tr); neg.append(sum(1 for v in mm.values() if v < 0) / max(1, len(mm)) * 100)
            R[sname] = dict(m=np.mean(ms), lo=min(ms), hi=max(ms), dd=np.mean(dds), wr=np.mean(wrs),
                            worst=np.mean(worst), neg=np.mean(neg))
        a, v = R["5y"], R["doğ"]
        print(f"{name:34s} | 5y aylık {a['m']:6,.0f} ({a['lo']:6,.0f}…{a['hi']:6,.0f}) isabet %{a['wr']:2.0f} "
              f"DD {a['dd']:7,.0f} eksi ay %{a['neg']:2.0f} | doğrulama aylık {v['m']:6,.0f} ({v['lo']:6,.0f}…{v['hi']:6,.0f}) DD {v['dd']:6,.0f}",
              flush=True)
        out.append((name, R))
    return out


if __name__ == "__main__" and "--robust" in sys.argv:
    print("\n=== SAĞLAM (kaydırmalı) ===")
    robust(VARIANTS + COMBOS)
