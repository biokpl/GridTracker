"""
select_research.py — DAHA İYİ HİSSE SEÇİMİ araştırması (2026-11-10).

Soru: VK3 havuzunda (günlük ilk 15 aday, ATR%≥3) #1'i 'momentum' yerine başka bir
gösterge / birleşik skorla seçmek 3 günlük işlem sonucunu iyileştirir mi?

Yöntem (yoldan bağımsız, aşırı uyuma karşı):
  • Her gün × her aday için varsayımsal VK3 işlemi (ertesi açılış, %5/%7, 3 gün) → getiri %
  • EĞİTİM (ilk %60): her göstergenin getiriyle sıra korelasyonu (IC) ölçülür
  • Birleşik skor = eğitimde anlamlı göstergelerin işaretli sıra ortalaması (ağırlık öğrenilmez)
  • DOĞRULAMA (son %40): her gün #1 seçimi → ortalama getiri, momentum ile kıyas
"""
import pickle
from pathlib import Path
import numpy as np
from scipy import stats

BASE = Path(__file__).parent
data = pickle.loads((BASE / "_ert_data_5y.pkl").read_bytes())
C = pickle.loads((BASE / "_sr_cands_5y.pkl").read_bytes())
days = sorted(C); idx = data["XU100"].index; N = len(idx)
xu = data["XU100"]["Close"].to_numpy(float)
sma20 = data["XU100"]["Close"].rolling(20).mean().to_numpy(float)
ARR = {}
def arr(s):
    if s not in ARR:
        df = data[s]; ARR[s] = {k: df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close")}
    return ARR[s]

def trade(sym, t):
    a = arr(sym)
    if t + 1 >= N: return None
    e = a["Open"][t + 1]
    if not (np.isfinite(e) and e > 0): return None
    S, T = e * .93, e * 1.05
    for k in range(4):
        d = t + 1 + k
        if d >= N: return None
        o, h, l, c = a["Open"][d], a["High"][d], a["Low"][d], a["Close"][d]
        if not np.isfinite(c): return None
        if l <= S: return ((min(S, o) if k else S) / e - 1) * 100
        if h >= T: return ((max(T, o) if k else T) / e - 1) * 100
        if k == 3: return (c / e - 1) * 100

FEATS = ["s_momentum", "s_technical", "s_rel_strength", "s_volume", "s_risk", "s_timing",
         "total_score", "entry_score", "rsi", "bb_pos", "atr_pct", "vol_ratio", "r5", "r20", "r60",
         "beta", "mdd_60", "rr_ratio"]

rows = []   # (t, feats dict, ret)
for t in days:
    pool = [c for c in C[t]["cands"] if (c.get("atr_pct") or 0) >= 3.0]
    for c in pool:
        r = trade(c["symbol"], t)
        if r is not None:
            rows.append((t, c, r))
cut = days[int(len(days) * .6)]
tr_rows = [x for x in rows if x[0] < cut]; va_rows = [x for x in rows if x[0] >= cut]
print(f"{len(rows)} varsayımsal işlem (eğitim {len(tr_rows)}, doğrulama {len(va_rows)})")

def daily_rank_ic(rws, f):
    """Her gün içinde göstergenin sırası ile getiri sırası korelasyonu → günlerin ortalaması."""
    by = {}
    for t, c, r in rws:
        v = c.get(f)
        if v is not None: by.setdefault(t, []).append((v, r))
    ics = [stats.spearmanr(*zip(*x))[0] for x in by.values() if len(x) >= 4]
    ics = [i for i in ics if np.isfinite(i)]
    return np.mean(ics), np.mean(ics) / (np.std(ics) / np.sqrt(len(ics)))

print("\nGösterge          | eğitim IC (t)        | doğrulama IC (t)")
ic = {}
for f in FEATS:
    a, ta = daily_rank_ic(tr_rows, f); b, tb = daily_rank_ic(va_rows, f); ic[f] = (a, ta)
    print(f"{f:17s} | {a:+.3f} (t={ta:+.1f})      | {b:+.3f} (t={tb:+.1f})")

sel = [f for f, (a, ta) in ic.items() if abs(ta) >= 2.0]
print("\nEğitimde anlamlı (|t|≥2):", ", ".join(f"{f}{'+' if ic[f][0] > 0 else '−'}" for f in sel))

def pick_eval(rws, key, gate=False):
    by = {}
    for t, c, r in rws:
        if gate and not (xu[t] >= sma20[t]): continue
        by.setdefault(t, []).append((c, r))
    res = []
    for t, lst in by.items():
        best = max(lst, key=lambda x: key(x[0], lst))
        res.append(best[1])
    res = np.array(res)
    return res.mean(), (res > 0).mean() * 100, len(res)

def rankkey(feats):
    def k(c, lst):
        s = 0
        for f in feats:
            vals = sorted((x[0].get(f) or 0) for x in lst)
            rk = np.searchsorted(vals, c.get(f) or 0) / max(1, len(vals) - 1)
            s += rk if ic[f][0] > 0 else (1 - rk)
        return s
    return k

mom = lambda c, lst: c.get("s_momentum") or 0
print("\n#1 seçimi → 3 günlük işlem ortalaması (doğrulama dönemi, endeks filtresi açık)")
for name, key in [("Momentum (şu anki)", mom), ("Birleşik skor (anlamlılar)", rankkey(sel))] + \
                 [(f"Tek: {f}", rankkey([f])) for f in sel]:
    a = pick_eval(tr_rows, key, True); b = pick_eval(va_rows, key, True)
    print(f"  {name:30s} eğitim %{a[0]:+.2f} (isabet %{a[1]:.0f}) | doğrulama %{b[0]:+.2f} (isabet %{b[1]:.0f}, {b[2]} gün)")
