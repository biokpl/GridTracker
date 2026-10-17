"""robustness.py — Trend stratejisinin sağlamlık kontrolleri (araştırma çıktısı)."""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np, pandas as pd
import crypto_research as cr

C, U = cr.C, cr.USDTRY
TR, TE = cr.TRAIN, cr.TEST

# 1) Kur etkisi: test döneminde sadece USDT tutmak TL bazında ne kazandırdı?
fx = U.loc[TE[0]:]
print(f"USDTRY: {fx.iloc[0]:.2f} → {fx.iloc[-1]:.2f}  (sadece USDT tutmak TL bazında {(fx.iloc[-1]/fx.iloc[0]-1)*100:+.0f}%)")
infl_tl = (fx.iloc[-1] / fx.iloc[0])

# 2) Komşu ayarlar: BTC+ETH trend ve BTC trend için TÜM N değerleri
print("\n── Ayar sağlamlığı (komşu ayarlar da iyi mi?) ──")
print(f"{'strateji':16s} {'N':>4s} │ {'eğitim Sharpe':>13s} {'eğitim düşüş':>12s} │ {'test yıllık':>11s} {'test düşüş':>10s} {'test Sharpe':>11s} {'işlem/yıl':>9s}")
for name, fn in (("BTC+ETH trend", lambda n: cr.s_trend_pair(n)), ("BTC trend", lambda n: cr.s_trend_sma("BTC", n))):
    for n in (20, 30, 40, 50, 60, 75, 100, 150, 200):
        W = fn(n); r = cr.run_weights(W)
        a, b = cr.stats(r, *TR), cr.stats(r, *TE)
        trades = (W.diff().abs().sum(axis=1) > 0).loc[TE[0]:].sum() / (len(W.loc[TE[0]:]) / 365)
        print(f"{name:16s} {n:4d} │ {a['sharpe']:13.2f} {a['dd']*100:11.0f}% │ {b['cagr']*100:+10.0f}% {b['dd']*100:9.0f}% {b['sharpe']:11.2f} {trades:9.1f}")

# 3) Yıl yıl: seçilen BTC+ETH trend(50) vs BTC al-tut (USD bazında)
print("\n── Yıl yıl getiri (USD bazında) ──")
r_tr = cr.run_weights(cr.s_trend_pair(50)); r_bh = cr.run_weights(cr.s_buyhold("BTC"))
for y in range(2019, 2027):
    a = (1 + r_tr.loc[str(y)]).prod() - 1; b = (1 + r_bh.loc[str(y)]).prod() - 1
    tag = "  ← eğitim" if y <= 2022 else ("  ← eğitim/test" if y == 2023 else "  ← TEST")
    print(f"  {y}: trend {a*100:+6.0f}%   BTC al-tut {b*100:+6.0f}%{tag}")

# 4) Son 12 ay ve bugünkü durum
last = r_tr.loc[str(C.index[-1] - pd.Timedelta(days=365)):]
eq = (1 + last).cumprod()
print(f"\nSon 12 ay trend(50): {(eq.iloc[-1]-1)*100:+.0f}%  max düşüş {((eq/eq.cummax())-1).min()*100:.0f}%  "
      f"| BTC al-tut {((1+r_bh.loc[last.index]).prod()-1)*100:+.0f}%")
for a in ("BTC", "ETH"):
    s = cr.sma(C[a], 50).iloc[-1]; c = C[a].iloc[-1]
    print(f"Bugün {a}: {c:,.0f} $  SMA50 {s:,.0f} $ → {'İÇERİDE (al)' if c > s else 'NAKİTTE (bekle)'}  ({(c/s-1)*100:+.1f}%)")

# 5) TL bazında 10.000 TL, kur etkisi ayrıştırılmış
te = cr.stats(r_tr, *TE)
print(f"\n10.000 TL (test dönemi, {te['months']} ay): TL sonuç {10000*(1+te['total_tl']):,.0f} TL"
      f"  = kur etkisi ×{infl_tl:.2f} + strateji ×{1+te['total']:.2f} (USD)")
print(f"  USD bazında aylık ort. bileşik: %{((1+te['total'])**(1/te['months'])-1)*100:.1f}"
      f" | TL bazında: %{((1+te['total_tl'])**(1/te['months'])-1)*100:.1f}")
print(f"  En kötü düşüş zirveden %{te['dd']*100:.0f} → 10 bin TL'lik zirvede ≈ −{-te['dd']*10000:,.0f} TL")
