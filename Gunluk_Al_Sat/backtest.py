"""
backtest.py — Günlük AL/SAT skorlama mantığını GEÇMİŞ veride test eder.

Amaç: bb<0.70, R/K≥1.0, RSI<70, entry≥3.0, konviksiyon vb. eşikleri TAHMİNLE
değil VERİYLE değerlendirmek. Tek-pozisyon, rotasyonlu (kullanıcının gerçek
akışı) simülasyon:
  • Her gün flat isek eligible'lardan #1'i (entry skoru) seç → o günün kapanışında gir
  • Pozisyondayken: target1'e değdi=KÂR, stop'a değdi=ZARAR, MAX_HOLD gün=zaman çıkışı
  • Çıkışta sıradakine geç

SADIK ÇEKİRDEK: advisor.score_stock olduğu gibi kullanılır. Sadece canlı-veri
çeken iki yardımcı geçmişe-uygun hale getirilir:
  • _event_risk → nötr (0) — bilanço/temettü takvimi geçmiş için güvenilmez
  • _weekly_trend → o güne kadarki günlük diliminden haftalık yeniden örnekleme

Kullanım:  python backtest.py            (varsayılan ~18 ay, MAX_HOLD=5)
           python backtest.py --bb 0.85  (eşik taraması: bb filtresini değiştir)
"""
import sys, json, argparse
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
import advisor  # skorlama çekirdeği

CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
SYMBOLS = CFG["bist100"]
SECTORS = CFG["sectors"]
COMM    = CFG.get("commission_rate", 0.0001)

# ── SADIK-ÇEKİRDEK YAMASI: canlı-veri yardımcılarını geçmişe uygun yap ──────────
_BT_SLICES: dict[str, pd.DataFrame] = {}   # her iterasyonda t'ye kadarki dilim

def _bt_weekly_trend(sym):
    df = _BT_SLICES.get(sym)
    if df is None or len(df) < 50:
        return "yatay", 0.0
    try:
        c  = df["Close"].dropna()
        wk = c.resample("W").last().dropna()
        if len(wk) < 10:
            return "yatay", 0.0
        ma = wk.rolling(20, min_periods=8).mean().dropna()
        if len(ma) < 2:
            return "yatay", 0.0
        now  = float(ma.iloc[-1])
        prev = float(ma.iloc[-8]) if len(ma) >= 8 else float(ma.iloc[0])
        slope = (now - prev) / prev * 100 if prev else 0.0
        if slope > 2.5:  return "yukari", round(slope, 1)
        if slope < -2.5: return "asagi",  round(slope, 1)
        return "yatay", round(slope, 1)
    except Exception:
        return "yatay", 0.0

advisor._weekly_trend = _bt_weekly_trend
advisor._event_risk   = lambda sym, df: (0.0, "")


def _download():
    print(f"[BT] {len(SYMBOLS)} sembol + XU100 indiriliyor (~2 yıl)...")
    tickers = [f"{s}.IS" for s in SYMBOLS] + ["XU100.IS"]
    raw = yf.download(tickers, period="2y", interval="1d",
                      auto_adjust=True, progress=False, threads=True)
    data = {}
    for s in SYMBOLS + ["XU100"]:
        t = f"{s}.IS"
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                df = raw.xs(t, axis=1, level=1)
            else:
                df = raw
            df = df.dropna(how="all")
            if len(df) >= 80:
                data[s] = df
        except Exception:
            continue
    print(f"[BT] {len(data)-1 if 'XU100' in data else len(data)} sembol verisi hazır.")
    return data


def run(bb_max=0.70, rsi_max=70.0, rr_min=1.0, entry_min=3.0,
        total_no_trade=5.0, max_hold=5, use_regime=True, use_conv=True, quiet=False):
    data = _download()
    xu = data.get("XU100")
    if xu is None:
        print("[BT] XU100 verisi yok — iptal."); return
    idx = xu.index
    N = len(idx)
    warmup = 65
    trades = []
    cooldown = {}   # symbol -> exit_date (zarar molası)
    pos = None

    for t in range(warmup, N - 1):
        date = idx[t]
        # ── pozisyon yönetimi ──
        if pos is not None:
            df = data[pos["sym"]]
            try:
                hi = float(df["High"].iloc[t]); lo = float(df["Low"].iloc[t]); cl = float(df["Close"].iloc[t])
            except Exception:
                continue
            held = t - pos["entry_t"]
            ex = None
            if lo <= pos["stop"]:        ex = ("stop",   pos["stop"])
            elif hi >= pos["target1"]:   ex = ("hedef",  pos["target1"])
            elif held >= max_hold:       ex = ("zaman",  cl)
            if ex:
                reason, xpx = ex
                gross = (xpx / pos["entry"] - 1) * 100
                net   = gross - COMM * 2 * 100      # gidiş-dönüş komisyon
                trades.append({"sym": pos["sym"], "entry_date": str(pos["entry_date"].date()),
                               "exit_date": str(date.date()), "held": held, "reason": reason,
                               "pnl_pct": round(net, 2), "conv": pos.get("conv", "")})
                if net < 0:
                    cooldown[pos["sym"]] = date
                pos = None
            continue

        # ── flat: aday seç ──
        xu_sl = xu.iloc[:t + 1]
        if use_regime:
            try:
                regime, _ = advisor._market_regime(xu_sl)
            except Exception:
                regime = "RISK_ON"
            if regime == "RISK_OFF":
                continue

        # tüm dilimleri ayarla (weekly_trend yaması için) + getiriler
        all_ret = {"r5": {}, "r20": {}, "r60": {}}
        slices = {}
        for s in SYMBOLS:
            df = data.get(s)
            if df is None or t >= len(df):
                continue
            sl = df.iloc[:t + 1]
            if len(sl) < warmup:
                continue
            slices[s] = sl
            c = sl["Close"]
            all_ret["r5"][s]  = (float(c.iloc[-1]) / float(c.iloc[-6]) - 1) * 100  if len(c) > 5  else None
            all_ret["r20"][s] = (float(c.iloc[-1]) / float(c.iloc[-21]) - 1) * 100 if len(c) > 20 else None
            all_ret["r60"][s] = (float(c.iloc[-1]) / float(c.iloc[-61]) - 1) * 100 if len(c) > 60 else None
        _BT_SLICES.clear(); _BT_SLICES.update(slices)

        scores = []
        for s, sl in slices.items():
            try:
                scores.append(advisor.score_stock(s, sl, xu_sl, all_ret, SECTORS))
            except Exception:
                continue

        # zarar molası (7 takvim günü)
        cd = {s for s, d in cooldown.items() if (date - d).days <= 7}

        eligible = [x for x in scores
                    if x["timeframe"] != "ÖNERİLMEZ"
                    and x.get("entry_score", 0) >= entry_min
                    and x.get("bb_pos", 0.5) < bb_max
                    and x.get("rsi", 50) < rsi_max
                    and x.get("rr_ratio", 0) >= rr_min
                    and x["symbol"] not in cd]
        eligible.sort(key=lambda x: (x.get("entry_score", 0), x["total_score"]), reverse=True)
        if not eligible:
            continue
        best = eligible[0]
        if best["total_score"] < total_no_trade and best.get("entry_score", 0) < total_no_trade:
            # çok zayıfsa atla (no_trade benzeri) — entry de total de düşükse
            pass  # yine de en iyiyi al (günlük-aktif); istenirse 'continue' yapılır

        # giriş = o günün kapanışı
        entry = float(data[best["symbol"]]["Close"].iloc[t])
        pos = {"sym": best["symbol"], "entry": entry, "entry_t": t, "entry_date": date,
               "stop": best["stop_loss"], "target1": best["target1"],
               "conv": _conv_label(best)}

    _report(trades, dict(bb_max=bb_max, rsi_max=rsi_max, rr_min=rr_min,
                         entry_min=entry_min, max_hold=max_hold, use_regime=use_regime))
    return trades


def _conv_label(p):
    rr = p.get("rr_ratio", 1.0) or 1.0; es = p.get("entry_score", 0) or 0
    if   rr >= 1.8 and es >= 5.5: return "Güçlü"
    elif rr >= 1.4 and es >= 4.5: return "İyi"
    elif rr >= 1.2 and es >= 4.0: return "Orta"
    return "Temkinli"


def _report(trades, params):
    print("\n" + "=" * 60)
    print(f"BACKTEST SONUCU  ({params})")
    print("=" * 60)
    if not trades:
        print("Hiç işlem oluşmadı (filtreler çok katı olabilir)."); return
    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    loss = [p for p in pnls if p <= 0]
    n = len(trades)
    wr = len(wins) / n * 100
    avg_w = np.mean(wins) if wins else 0
    avg_l = np.mean(loss) if loss else 0
    pf = (sum(wins) / abs(sum(loss))) if loss and sum(loss) != 0 else float("inf")
    # bileşik getiri (sıralı tek-pozisyon → çarpımsal)
    comp = 1.0
    for p in pnls: comp *= (1 + p / 100)
    comp = (comp - 1) * 100
    reasons = {}
    for t in trades: reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    print(f"İşlem sayısı     : {n}")
    print(f"İsabet (win rate): {wr:.1f}%  ({len(wins)} kâr / {len(loss)} zarar)")
    print(f"Ort. kâr / zarar : +{avg_w:.2f}% / {avg_l:.2f}%")
    print(f"Profit Factor    : {pf:.2f}")
    print(f"Ort. işlem getiri: {np.mean(pnls):+.2f}%  | medyan {np.median(pnls):+.2f}%")
    print(f"BİLEŞİK getiri   : {comp:+.1f}%  (sıralı tek-pozisyon, ~2 yıl)")
    print(f"En iyi / en kötü : {max(pnls):+.2f}% / {min(pnls):+.2f}%")
    print(f"Çıkış sebepleri  : {reasons}")
    # konviksiyon kırılımı
    by = {}
    for t in trades:
        by.setdefault(t["conv"], []).append(t["pnl_pct"])
    print("--- Konviksiyona göre ---")
    for k in ["Güçlü", "İyi", "Orta", "Temkinli"]:
        if k in by:
            v = by[k]; w = len([x for x in v if x > 0]) / len(v) * 100
            print(f"  {k:9s}: {len(v):3d} işlem | isabet {w:.0f}% | ort {np.mean(v):+.2f}%")
    print("=" * 60)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bb", type=float, default=0.70)
    ap.add_argument("--rsi", type=float, default=70.0)
    ap.add_argument("--rr", type=float, default=1.0)
    ap.add_argument("--entry", type=float, default=3.0)
    ap.add_argument("--hold", type=int, default=5)
    ap.add_argument("--noregime", action="store_true")
    args = ap.parse_args()
    run(bb_max=args.bb, rsi_max=args.rsi, rr_min=args.rr, entry_min=args.entry,
        max_hold=args.hold, use_regime=not args.noregime)
