"""voltarget.py — Trend stratejisine oynaklık hedeflemesi: piyasa çok oynakken
pozisyon küçülür (ağırlık = min(1, hedef_oynaklık / son 20 gün oynaklığı))."""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np, pandas as pd
import crypto_research as cr

C, RET = cr.C, cr.RET


def trend_vt(n, target, assets=("BTC", "ETH")):
    w = {}
    for a in assets:
        on = (C[a] > cr.sma(C[a], n)).astype(float)
        vol = RET[a].rolling(20).std() * np.sqrt(365)
        scale = (target / vol).clip(upper=1.0) if target else 1.0
        w[a] = on * scale / len(assets)
    return pd.DataFrame(w)


print(f"{'ayar':28s} │ {'eğitim yıllık':>13s} {'düşüş':>6s} {'Sharpe':>6s} │ {'TEST yıllık':>11s} {'düşüş':>6s} {'Sharpe':>6s} {'2022':>6s} {'ort. yatırım':>12s}")
for assets in (("BTC", "ETH"), ("BTC",)):
    for n in (40, 50):
        for tv in (None, 0.8, 0.6, 0.4):
            W = trend_vt(n, tv, assets); r = cr.run_weights(W)
            a, b = cr.stats(r, *cr.TRAIN), cr.stats(r, *cr.TEST)
            y22 = (1 + r.loc["2022"]).prod() - 1
            expo = W.sum(axis=1).loc[cr.TEST[0]:].mean()
            tag = f"{'+'.join(assets)} SMA{n} " + (f"hedef %{int(tv*100)}" if tv else "tam")
            print(f"{tag:28s} │ {a['cagr']*100:+12.0f}% {a['dd']*100:5.0f}% {a['sharpe']:6.2f} │ "
                  f"{b['cagr']*100:+10.0f}% {b['dd']*100:5.0f}% {b['sharpe']:6.2f} {y22*100:+5.0f}% {expo*100:11.0f}%")
