"""
old_vs_vk3.py — ESKİ canlı sistem (RK) ile VK3'ün aynı veride karşılaştırması (2026-10-23).

Eski sistem canlı ayarlarıyla taklit edilir:
  • Uygunluk: ÖNERİLMEZ değil, entry≥3.0, bb<0.65, rsi<65, 7 gün zarar molası
  • Seçim: giriş skoru (eşitse toplam skor)
  • Lot: sermaye × min(rejim, konviksiyon); rejim CAUTION/RISK_OFF=0.5;
    risk kısıtı stopta ≤1.000 TL, felaket stopta ≤1.500 TL
  • Çıkış: felaket stop (gün içi), stop (günlük kapanış altı ≈ saatlik kapanış onayı),
    hedef1 (gün içi), en fazla N gün (canlıda süre yok; N=5 varsayıldı)
  • Giriş: kapanış (canlıda gün içi canlı fiyatla giriliyordu)
VK3: strategy_research ile birebir (ertesi açılış, hedef %5, stop %7, 3 gün, tam sermaye).
"""
import sys
from pathlib import Path
import numpy as np

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
import exit_rules_test as E
import strategy_research as S

CAPITAL = 50_000.0
COMM = E.COMM


def old_system(data, cands, days, max_hold=5, capital=CAPITAL):
    idx = data["XU100"].index; N = len(idx)
    tr = []; pos = None; eq = pk = dd = 0.0; cooldown = {}
    t = days[0]; tmax = days[-1]; dset = set(days)
    while t <= tmax and t < N - 1:
        if pos is None:
            day = cands.get(t)
            if t in dset and day:
                el = [c for c in day["cands"]
                      if (c.get("entry_score") or 0) >= 3.0 and (c.get("bb_pos") or .5) < .65
                      and (c.get("rsi") or 50) < 65
                      and not (c["symbol"] in cooldown and (idx[t] - cooldown[c["symbol"]]).days <= 7)]
                el.sort(key=lambda c: ((c.get("entry_score") or 0), (c.get("total_score") or 0)), reverse=True)
                if el:
                    c = el[0]; e = c["close"]
                    rr = c.get("rr_ratio") or 1.0; es = c.get("entry_score") or 0
                    conv = 1.0 if (rr >= 1.8 and es >= 5.5) else .85 if (rr >= 1.4 and es >= 4.5) else .70 if (rr >= 1.2 and es >= 4.0) else .55
                    reg = .5 if day["regime"] in ("CAUTION", "RISK_OFF") else 1.0
                    q = capital * min(reg, conv) / e
                    stop = c["stop_loss"]; hard = stop - 0.5 * c["atr"]
                    for lim, ps in ((1000, e - stop), (1500, e - hard)):
                        if ps > 0 and lim / ps < q:
                            q = lim / ps
                    pos = dict(a=S._arr(data, c["symbol"]), e=e, q=q, t0=t, sym=c["symbol"],
                               stop=stop, hard=hard, tgt=c["target1"])
            t += 1; continue
        a = pos["a"]; op, hi, lo, cl = a["Open"][t], a["High"][t], a["Low"][t], a["Close"][t]
        held = t - pos["t0"]; ex = None
        if lo <= pos["hard"]:
            ex = min(pos["hard"], op)
        elif hi >= pos["tgt"]:
            ex = max(pos["tgt"], op) if op > pos["tgt"] else pos["tgt"]
        elif cl <= pos["stop"]:
            ex = cl
        elif held >= max_hold:
            ex = cl
        if ex is not None:
            pnl = (ex - pos["e"]) * pos["q"] - COMM * (ex + pos["e"]) * pos["q"]
            tr.append(dict(pnl=pnl, held=held, sym=pos["sym"], t=pos["t0"], cost=pos["e"] * pos["q"]))
            if pnl < 0:
                cooldown[pos["sym"]] = idx[t]
            eq += pnl; pk = max(pk, eq); dd = max(dd, pk - eq); pos = None
        t += 1
    return tr, dd


def line(name, tr, dd, ndays):
    if not tr:
        print(f"{name:44s} işlem yok"); return
    p = np.array([x["pnl"] for x in tr]); m = ndays / 21
    cost = np.mean([x.get("cost", CAPITAL) for x in tr])
    print(f"{name:44s} işlem {len(p):4d} ({len(p)/m:4.1f}/ay) | isabet %{(p>0).mean()*100:3.0f} | ort {p.mean():5.0f} TL | "
          f"aylık {p.sum()/m:6,.0f} | PF {p[p>0].sum()/max(1e-9, abs(p[p<=0].sum())):.2f} | en kötü {p.min():7,.0f} | DD {dd:7,.0f}"
          + (f" | ort poz {cost:,.0f}" if "cost" in tr[0] else ""))


def main():
    data = E.download(5); C = S.build_cands(data); days = sorted(C); idx = data["XU100"].index
    F, R = S.FILTERS["oynak: atr%≥3"], S.RANKS["momentum"]
    print("=== 5 YIL (2021-2026), 50.000 TL ===")
    for mh in (3, 5):
        line(f"ESKİ sistem (canlı ayarlar, max {mh} gün)", *old_system(data, C, days, mh), len(days))
    line("VK3 (açılış, %5/%7, 3 gün)", *S.simulate(data, C, days, F, R, (7.0, 5.0, 3), "open"), len(days))
    print("\n=== Yıl yıl (aylık ort TL) ===")
    for y in sorted({idx[d].year for d in days}):
        dy = [d for d in days if idx[d].year == y]
        o, _ = old_system(data, C, dy, 5); v, _ = S.simulate(data, C, dy, F, R, (7.0, 5.0, 3), "open")
        m = len(dy) / 21
        print(f"  {y}: ESKİ {sum(x['pnl'] for x in o)/m:6,.0f} TL/ay ({len(o)} işlem) | VK3 {sum(x['pnl'] for x in v)/m:6,.0f} TL/ay ({len(v)} işlem)")
    # gerçek karnenin olduğu dönem
    w = [d for d in days if "2026-05-29" <= str(idx[d].date()) <= "2026-07-20"]
    print(f"\n=== Gerçek karnenin dönemi ({idx[w[0]].date()} – {idx[w[-1]].date()}, {len(w)} gün) ===")
    print("  GERÇEK (canlı, Matriks): 22 işlem | isabet %59 | ort 510 TL | toplam 11.212 TL | ort poz ~66.000 TL")
    o, dd = old_system(data, C, w, 5, capital=66_000); line("  ESKİ backtest (66.000 TL)", o, dd, len(w))
    print(f"    toplam {sum(x['pnl'] for x in o):,.0f} TL")
    v, dd = S.simulate(data, C, w, F, R, (7.0, 5.0, 3), "open"); line("  VK3 backtest (50.000 TL)", v, dd, len(w))
    print(f"    toplam {sum(x['pnl'] for x in v):,.0f} TL")


if __name__ == "__main__":
    main()
