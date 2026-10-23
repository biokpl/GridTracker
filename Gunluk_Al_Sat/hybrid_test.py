"""
hybrid_test.py — Eski sistem (RK) + VK3 güçlerini birleştiren hibritler (2026-10-24).
Hepsi aynı aday havuzu (strategy_research cands), ertesi gün açılışta giriş, 50.000 TL,
eğitim (%60) / doğrulama (%40) ayrımı. VK3 = referans.
"""
import sys
from pathlib import Path
import numpy as np

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
import exit_rules_test as E
import strategy_research as S

data = E.download(5); C = S.build_cands(data); DAYS = sorted(C)
IDX = data["XU100"].index; N = len(IDX)
CUT = DAYS[int(len(DAYS) * .6)]
TRAIN = [d for d in DAYS if d < CUT]; TEST = [d for d in DAYS if d >= CUT]
g = S.g


def sim(days, filt, rank, exit_="vk3", regime="half_off", cooldown=False, stop_pct=7.0, tgt_pct=5.0, hold=3):
    """exit_: 'vk3' (%stop/%hedef) | 'old' (adayın yapısal stop/hedefi, felaket=stop−0.5ATR)
              | 'mix' (hedef %5, stop = max(yapısal felaket, −%7))
    regime : 'half_off' (RISK_OFF yarım) | 'half_weak' (CAUTION+RISK_OFF yarım) | 'skip_off' (RISK_OFF'ta işlem yok)"""
    tr = []; pos = None; eq = pk = dd = 0.0; cd = {}; dset = set(days); t = days[0]
    while t <= days[-1] and t < N - 1:
        if pos is None:
            day = C.get(t)
            if t in dset and day and not (regime == "skip_off" and day["regime"] == "RISK_OFF"):
                el = [c for c in day["cands"] if filt(c)
                      and not (cooldown and c["symbol"] in cd and (IDX[t] - cd[c["symbol"]]).days <= 7)]
                if el:
                    c = max(el, key=rank); a = S._arr(data, c["symbol"]); e = a["Open"][t + 1]
                    if np.isfinite(e) and e > 0:
                        weak = day["regime"] == "RISK_OFF" or (regime == "half_weak" and day["regime"] == "CAUTION")
                        q = S.CAPITAL * (0.5 if weak else 1.0) / e
                        # yapısal seviyeleri açılış fiyatına oranla taşı
                        k = e / c["close"]
                        if exit_ == "old":
                            st = (c["stop_loss"] - 0.5 * c["atr"]) * k; tg = c["target1"] * k
                        elif exit_ == "mix":
                            st = max((c["stop_loss"] - 0.5 * c["atr"]) * k, e * (1 - stop_pct / 100)); tg = e * (1 + tgt_pct / 100)
                        else:
                            st = e * (1 - stop_pct / 100); tg = e * (1 + tgt_pct / 100)
                        pos = dict(a=a, e=e, q=q, t0=t + 1, stop=st, tgt=tg, sym=c["symbol"])
            t += 1; continue
        a = pos["a"]; op, hi, lo, cl = a["Open"][t], a["High"][t], a["Low"][t], a["Close"][t]
        held = t - pos["t0"]; gap = held > 0; ex = None
        if lo <= pos["stop"]: ex = min(pos["stop"], op) if gap else pos["stop"]
        elif hi >= pos["tgt"]: ex = max(pos["tgt"], op) if gap else pos["tgt"]
        elif held >= hold: ex = cl
        if ex is not None:
            pnl = (ex - pos["e"]) * pos["q"] - S.COMM * (ex + pos["e"]) * pos["q"]
            tr.append(pnl)
            if pnl < 0: cd[pos["sym"]] = IDX[t]
            eq += pnl; pk = max(pk, eq); dd = max(dd, pk - eq); pos = None
        t += 1
    return np.array(tr), dd


def st(p, dd, n):
    m = n / 21
    return dict(n=len(p), avg=p.mean() if len(p) else 0, month=p.sum() / m if len(p) else 0,
                pf=p[p > 0].sum() / max(1e-9, abs(p[p <= 0].sum())) if len(p) else 0,
                wr=(p > 0).mean() * 100 if len(p) else 0, dd=dd, worst=p.min() if len(p) else 0)


ATR3 = lambda c: g(c, "atr_pct") >= 3
OLDF = lambda c: g(c, "entry_score") >= 3 and g(c, "bb_pos", .5) < .65 and g(c, "rsi", 50) < 65
MOM = lambda c: g(c, "s_momentum")
ENT = lambda c: (g(c, "entry_score"), g(c, "total_score"))
MIX = lambda c: g(c, "s_momentum") + g(c, "entry_score")          # momentum + giriş kalitesi
MIX2 = lambda c: g(c, "s_momentum") + 0.5 * g(c, "total_score")

VARIANTS = [
    ("VK3 (referans)",                                   dict(filt=ATR3, rank=MOM)),
    ("ESKİ seçim + VK3 çıkış",                           dict(filt=OLDF, rank=ENT)),
    ("H1 oynak + eski filtreler, momentum",              dict(filt=lambda c: ATR3(c) and OLDF(c), rank=MOM)),
    ("H2 eski filtreler, momentum sırası",               dict(filt=OLDF, rank=MOM)),
    ("H3 oynak + eski filtreler, giriş skoru",           dict(filt=lambda c: ATR3(c) and OLDF(c), rank=ENT)),
    ("H4 oynak, momentum+giriş skoru",                   dict(filt=ATR3, rank=MIX)),
    ("H5 oynak, momentum+½toplam",                       dict(filt=ATR3, rank=MIX2)),
    ("H6 VK3 + zarar molası",                            dict(filt=ATR3, rank=MOM, cooldown=True)),
    ("H7 VK3 + zayıf piyasada (CAUTION) yarım",          dict(filt=ATR3, rank=MOM, regime="half_weak")),
    ("H8 VK3 + RISK_OFF'ta işlem yok",                   dict(filt=ATR3, rank=MOM, regime="skip_off")),
    ("H9 VK3 seçim + ESKİ yapısal stop/hedef",           dict(filt=ATR3, rank=MOM, exit_="old")),
    ("H10 VK3 seçim + hedef %5, stop yapısal (≤%7)",     dict(filt=ATR3, rank=MOM, exit_="mix")),
    ("H11 oynak + RSI<65, momentum",                     dict(filt=lambda c: ATR3(c) and g(c, "rsi", 50) < 65, rank=MOM)),
    ("H12 oynak + bb<0.65, momentum",                    dict(filt=lambda c: ATR3(c) and g(c, "bb_pos", .5) < .65, rank=MOM)),
    ("H13 oynak + entry≥3, momentum",                    dict(filt=lambda c: ATR3(c) and g(c, "entry_score") >= 3, rank=MOM)),
    ("H14 H6+H13 (zarar molası + entry≥3)",              dict(filt=lambda c: ATR3(c) and g(c, "entry_score") >= 3, rank=MOM, cooldown=True)),
]

if __name__ == "__main__":
    print(f"eğitim {IDX[TRAIN[0]].date()}–{IDX[TRAIN[-1]].date()} | doğrulama {IDX[TEST[0]].date()}–{IDX[TEST[-1]].date()}\n")
    print(f"{'varyant':46s} | {'EĞİTİM ort/aylık/PF':>20s} | {'DOĞRULAMA ort/aylık/PF':>23s} | 5y: işlem isabet  aylık    DD   en kötü")
    for name, kw in VARIANTS:
        a = st(*sim(TRAIN, **kw), len(TRAIN)); b = st(*sim(TEST, **kw), len(TEST)); c = st(*sim(DAYS, **kw), len(DAYS))
        print(f"{name:46s} | {a['avg']:5.0f} {a['month']:6,.0f} {a['pf']:4.2f} | {b['avg']:5.0f} {b['month']:6,.0f} {b['pf']:4.2f}      | "
              f"{c['n']:4d} %{c['wr']:3.0f} {c['month']:6,.0f} {c['dd']:7,.0f} {c['worst']:7,.0f}")
