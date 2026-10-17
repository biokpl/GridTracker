"""
crypto_research.py — Kripto (spot, kaldıraçsız) strateji araştırması.

Yöntem (Haziran'daki lookahead hatasını tekrarlamamak için):
  • Sinyal t günü KAPANIŞIYLA hesaplanır, pozisyon t→t+1 getirisine uygulanır
    (geleceği görmez).
  • Maliyet: her ağırlık değişiminde binde 1 komisyon + binde 0,5 kayma.
  • EĞİTİM (2019-07 → 2023-06): her strateji ailesinin ayarları burada seçilir.
  • TEST   (2023-07 → bugün):   seçilen ayar HİÇ görmediği bu dönemde ölçülür.
    Rapor edilen başarı TEST dönemidir.
  • Seçim ölçütü: Sharpe (getiri/oynaklık) — "en çok kazandıran" ayar geçmişe
    aşırı uyar; risk-düzeltmeli ölçüt daha sağlam genellenir.
  • Nakit = USDT (dolar). TL karşılığı USDTRY ile hesaplanır.
"""
import sys, itertools
from pathlib import Path
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
COST = 0.0015            # komisyon 0.10% + kayma 0.05% (tek yön, ağırlık değişimi başına)
TRAIN = ("2019-07-01", "2023-06-30")
TEST  = ("2023-07-01", "2099-01-01")
CAPITAL_TL = 10_000

raw = pd.read_pickle(BASE / "data_raw.pkl")
C = raw["Close"].copy(); H = raw["High"].copy(); L = raw["Low"].copy()
C.columns = [c.replace("-USD", "") for c in C.columns]
H.columns = [c.replace("-USD", "") for c in H.columns]
L.columns = [c.replace("-USD", "") for c in L.columns]
USDTRY = C.pop("USDTRY=X").ffill(); H.pop("USDTRY=X"); L.pop("USDTRY=X")
for bad in ("ARB",):                       # erken verisi farklı bir tokene ait
    for df in (C, H, L):
        df.drop(columns=bad, inplace=True, errors="ignore")
# Yahoo'nun kripto günlerinde boşluk yok; USDTRY hafta sonu ffill
C = C.loc["2019-01-01":]; H = H.reindex(C.index); L = L.reindex(C.index)
USDTRY = USDTRY.reindex(C.index).ffill()
RET = C.pct_change()
COINS = list(C.columns)


# ── yardımcılar ──────────────────────────────────────────────────────────────
def sma(s, n): return s.rolling(n, min_periods=n).mean()
def ema(s, n): return s.ewm(span=n, adjust=False, min_periods=n).mean()
def rsi(s, n):
    d = s.diff(); up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def run_weights(W: pd.DataFrame) -> pd.Series:
    """W: t günü kapanışında belirlenen hedef ağırlıklar (satır toplamı ≤1).
    Günlük net portföy getirisi (USD bazında) döner."""
    W = W.reindex(C.index).fillna(0.0)
    gross = (W.shift(1) * RET.reindex(columns=W.columns)).sum(axis=1)
    turnover = W.diff().abs().sum(axis=1).fillna(W.abs().sum(axis=1))
    return gross - turnover.shift(1).fillna(0) * COST


def stats(r: pd.Series, a, b):
    r = r.loc[a:b].dropna()
    if len(r) < 30:
        return None
    eq = (1 + r).cumprod()
    yrs = len(r) / 365
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    sharpe = r.mean() / r.std() * np.sqrt(365) if r.std() > 0 else 0
    m = (1 + r).resample("ME").prod() - 1
    # TL bazında (nakit USDT, değer TL'ye çevrilir)
    fx = USDTRY.loc[r.index]
    eq_tl = eq * fx / fx.iloc[0]
    exposure = None
    return {"total": eq.iloc[-1] - 1, "cagr": cagr, "dd": dd, "sharpe": sharpe,
            "pos_m": (m > 0).mean(), "worst_m": m.min(), "best_m": m.max(),
            "total_tl": eq_tl.iloc[-1] - 1, "months": len(m), "eq": eq}


# ── STRATEJİ AİLELERİ (her biri ayar → ağırlık matrisi) ──────────────────────
def s_buyhold(asset="BTC"):
    return pd.DataFrame({asset: 1.0}, index=C.index)


def s_trend_sma(asset, n):
    """Fiyat N günlük ortalamanın üstündeyse tut, altındaysa nakit."""
    sig = (C[asset] > sma(C[asset], n)).astype(float)
    return pd.DataFrame({asset: sig})


def s_trend_pair(n):
    """BTC ve ETH için ayrı ayrı SMA trend filtresi, yarı yarıya."""
    w = {a: 0.5 * (C[a] > sma(C[a], n)).astype(float) for a in ("BTC", "ETH")}
    return pd.DataFrame(w)


def s_ema_cross(asset, f, s):
    sig = (ema(C[asset], f) > ema(C[asset], s)).astype(float)
    return pd.DataFrame({asset: sig})


def s_donchian(asset, n_in, n_out):
    """Kırılım: N günlük zirve kırılınca gir, M günlük dip kırılınca çık."""
    hi = H[asset].rolling(n_in).max().shift(1)
    lo = L[asset].rolling(n_out).min().shift(1)
    c = C[asset]; pos = np.zeros(len(c)); p = 0
    for i in range(len(c)):
        if np.isnan(hi.iloc[i]) or np.isnan(c.iloc[i]):
            pos[i] = p; continue
        if p == 0 and c.iloc[i] > hi.iloc[i]: p = 1
        elif p == 1 and c.iloc[i] < lo.iloc[i]: p = 0
        pos[i] = p
    return pd.DataFrame({asset: pos}, index=C.index)


def s_momentum(lookback, top_k, reb, btc_filter, coin_filter=50):
    """Momentum rotasyonu: her `reb` günde bir son `lookback` gün getirisi en
    yüksek `top_k` coin (kendi `coin_filter` SMA'sı üstünde olanlardan) eşit
    ağırlık. btc_filter>0 ise BTC kendi SMA'sının altındayken TAMAMEN nakit."""
    mom = C / C.shift(lookback) - 1
    above = C > sma(C, coin_filter) if coin_filter else C.notna()
    btc_ok = (C["BTC"] > sma(C["BTC"], btc_filter)) if btc_filter else pd.Series(True, index=C.index)
    # yeterli geçmişi olmayan (yeni listelenen) coin hariç
    seasoned = C.notna().rolling(120).sum() >= 120
    W = pd.DataFrame(0.0, index=C.index, columns=COINS)
    last = None
    for i, d in enumerate(C.index):
        if i < max(lookback, 200):
            continue
        if last is not None and (i - last) < reb and btc_ok.iloc[i]:
            W.iloc[i] = W.iloc[i - 1]; continue
        last = i
        if not btc_ok.iloc[i]:
            continue
        cand = mom.iloc[i][(above.iloc[i]) & (seasoned.iloc[i])].dropna()
        cand = cand[cand > 0].sort_values(ascending=False).head(top_k)
        if len(cand):
            W.loc[d, cand.index] = 1.0 / top_k      # dolmayan slotlar nakit
    return W


def s_rsi2(asset, thr, trend=200):
    """Kısa vade geri dönüş: trend yukarıyken (>SMA200) RSI(2)<thr ise al,
    kapanış SMA(5) üstüne çıkınca sat."""
    c = C[asset]; r2 = rsi(c, 2); up = c > sma(c, trend); ex = c > sma(c, 5)
    pos = np.zeros(len(c)); p = 0
    for i in range(len(c)):
        if p == 0 and up.iloc[i] and r2.iloc[i] < thr: p = 1
        elif p == 1 and (ex.iloc[i] or not up.iloc[i]): p = 0
        pos[i] = p
    return pd.DataFrame({asset: pos}, index=C.index)


def s_combo(n_trend, lookback, top_k):
    """%50 BTC trend + %50 momentum rotasyonu (BTC>SMA filtresiyle)."""
    a = s_trend_sma("BTC", n_trend) * 0.5
    b = s_momentum(lookback, top_k, 7, n_trend) * 0.5
    return a.reindex(columns=COINS).fillna(0).add(b, fill_value=0)


FAMILIES = {
    "BTC al-tut (kıyas)":       (s_buyhold, [("BTC",)]),
    "BTC trend (SMA)":          (s_trend_sma, [("BTC", n) for n in (20, 50, 100, 150, 200)]),
    "ETH trend (SMA)":          (s_trend_sma, [("ETH", n) for n in (20, 50, 100, 150, 200)]),
    "BTC+ETH trend":            (s_trend_pair, [(n,) for n in (20, 50, 100, 150, 200)]),
    "BTC EMA kesişim":          (s_ema_cross, [("BTC", f, s) for f, s in ((10, 30), (12, 26), (20, 50), (50, 200))]),
    "BTC kırılım (Donchian)":   (s_donchian, [("BTC", a, b) for a, b in ((20, 10), (55, 20), (20, 20), (55, 55))]),
    "ETH kırılım (Donchian)":   (s_donchian, [("ETH", a, b) for a, b in ((20, 10), (55, 20), (20, 20), (55, 55))]),
    "Momentum rotasyon":        (s_momentum, [(lb, k, rb, bf) for lb, k, rb, bf in itertools.product(
                                    (14, 30, 60, 90), (1, 3, 5), (7,), (0, 100, 200))]),
    "BTC RSI(2) geri dönüş":    (s_rsi2, [("BTC", t) for t in (5, 10, 20)]),
    "BTC trend + momentum":     (s_combo, [(n, lb, k) for n, lb, k in itertools.product((100, 200), (30, 60), (3, 5))]),
}


def main():
    rows, best_eq = [], {}
    for fam, (fn, grid) in FAMILIES.items():
        best = None
        for params in grid:
            r = run_weights(fn(*params))
            tr = stats(r, *TRAIN)
            if tr is None:
                continue
            if best is None or tr["sharpe"] > best[1]["sharpe"]:
                best = (params, tr, r)
        params, tr, r = best
        te = stats(r, *TEST)
        rows.append((fam, params, tr, te))
        best_eq[fam] = te["eq"]
        print(f"[✓] {fam:24s} seçilen ayar {params}")

    print("\n" + "═" * 112)
    print(f"{'STRATEJİ':24s} {'AYAR':22s} │ {'EĞİTİM Sharpe':>13s} │ "
          f"{'TEST: yıllık':>12s} {'toplam':>8s} {'TL top.':>8s} {'max düşüş':>9s} "
          f"{'Sharpe':>6s} {'+ay':>5s} {'en kötü ay':>10s}")
    print("─" * 112)
    for fam, p, tr, te in sorted(rows, key=lambda x: -x[3]["sharpe"]):
        print(f"{fam:24s} {str(p):22s} │ {tr['sharpe']:13.2f} │ "
              f"{te['cagr']*100:+11.0f}% {te['total']*100:+7.0f}% {te['total_tl']*100:+7.0f}% "
              f"{te['dd']*100:8.0f}% {te['sharpe']:6.2f} {te['pos_m']*100:4.0f}% {te['worst_m']*100:+9.0f}%")
    print("═" * 112)
    m = rows[0][3]["months"]
    print(f"TEST dönemi: {TEST[0]} → {C.index[-1].date()} ({m} ay). Maliyet: işlem başı %{COST*100:.2f}.")
    # 10 bin TL ile ay ay TL kazanç (en iyi 3 Sharpe)
    print("\n10.000 TL ile TEST döneminde (TL bazında, bileşik):")
    for fam, p, tr, te in sorted(rows, key=lambda x: -x[3]["sharpe"])[:5]:
        end = CAPITAL_TL * (1 + te["total_tl"])
        print(f"  {fam:24s}: 10.000 → {end:>10,.0f} TL  | ayda ort. bileşik "
              f"%{((1+te['total_tl'])**(1/te['months'])-1)*100:.1f}  | en kötü düşüşte "
              f"−{-te['dd']*CAPITAL_TL:,.0f} TL (başlangıca göre)")
    pd.DataFrame(best_eq).to_pickle(BASE / "test_equity.pkl")


if __name__ == "__main__":
    main()
