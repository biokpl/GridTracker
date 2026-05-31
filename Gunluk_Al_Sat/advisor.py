"""
advisor.py — BIST100 Günlük Sermaye Danışmanı  (Skor: 0-10)
Kullanım:
  python advisor.py --run    Tam analiz + result.json + push bildirimi
  python advisor.py --test   Analiz yap, hiçbir şey yazma/gönderme
  python advisor.py --check  Sadece aktif pozisyon çıkış kontrolü + push
  python advisor.py --symbol THYAO  Tek hisse detayı
"""
import argparse
import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

# Windows terminali UTF-8 yapılıyor
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

BASE         = Path(__file__).parent
CFG          = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
STATE_PATH   = BASE / "state.json"
RESULT_PATH  = Path(CFG["result_path"])
FIREBASE_URL = "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app"


def _firebase_push(result: dict):
    """Özet veriyi Firebase'e yazar (telefon erişimi için)."""
    import requests as _req

    # Firebase'e gönderilecek özet (score_table hariç — çok büyük)
    payload = {
        "ts":          result["ts"],
        "ts_str":      result["ts_str"],
        "capital":     result["capital"],
        "top_picks":   result["top_picks"],
        "exit_signal": result["exit_signal"],
        "lot_info":    result["lot_info"],
        "tracker":     result["tracker"],
    }
    try:
        url = f"{FIREBASE_URL}/gridtracker/advisor.json"
        r = _req.put(url, json=payload, timeout=10)
        if r.status_code == 200:
            print("[Advisor] Firebase güncellendi.")
        else:
            print(f"[Advisor] Firebase hatası: {r.status_code}")
    except Exception as e:
        print(f"[Advisor] Firebase bağlantı hatası: {e}")

# Puan tavanları (ham, 100 üzerinden — sonra /10 ile normalize)
_RAW_MAX = 100.0


# ─── Yardımcılar ─────────────────────────────────────────────────────────────

def _load_state() -> dict:
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _ts_str(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


def _pct(a, b) -> float:
    return (a - b) / b * 100 if b else 0.0


def calc_lots(capital: float, price: float, commission_rate: float = 0.0001) -> int:
    """Sermaye ve fiyatla alınabilecek lot sayısı (komisyon dahil)."""
    if price <= 0 or capital <= 0:
        return 0
    cost_per_lot = price * (1 + commission_rate)
    return int(capital / cost_per_lot)


def calc_capital_after_sell(qty: int, price: float, commission_rate: float = 0.0001) -> float:
    """Satış sonrası elde edilecek net sermaye."""
    gross = qty * price
    commission = gross * commission_rate
    return gross - commission


# ─── Teknik Göstergeler ──────────────────────────────────────────────────────

def _rsi(close: pd.Series, n: int = 14) -> float:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(n).mean()
    loss  = (-delta.clip(upper=0)).rolling(n).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - 100 / (1 + rs)
    v = float(rsi.iloc[-1])
    return v if not np.isnan(v) else 50.0


def _macd(close: pd.Series) -> tuple[float, float]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    sig   = macd.ewm(span=9, adjust=False).mean()
    return float(macd.iloc[-1]), float(sig.iloc[-1])


def _bollinger(close: pd.Series, n: int = 20) -> tuple[float, float, float]:
    mid = close.rolling(n).mean()
    std = close.rolling(n).std()
    return float(mid.iloc[-1]), float((mid + 2*std).iloc[-1]), float((mid - 2*std).iloc[-1])


def _atr(df: pd.DataFrame, n: int = 14) -> float:
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return float(tr.rolling(n).mean().iloc[-1])


def _beta(stock_ret: pd.Series, index_ret: pd.Series, n: int = 60) -> float:
    aligned = pd.concat([stock_ret, index_ret], axis=1).dropna().iloc[-n:]
    if len(aligned) < 20:
        return 1.0
    cov = aligned.cov().iloc[0, 1]
    var = aligned.iloc[:, 1].var()
    return float(cov / var) if var else 1.0


def _max_drawdown(close: pd.Series, n: int = 60) -> float:
    c = close.iloc[-n:]
    roll_max = c.cummax()
    dd = (c - roll_max) / roll_max
    return float(dd.min()) * -1


def _zscore(val: float, values: list[float]) -> float:
    arr = np.array(values)
    mu, sigma = arr.mean(), arr.std()
    if sigma == 0:
        return 0.0
    return float((val - mu) / sigma)


def _clamp(x, lo=0.0, hi=1.0) -> float:
    return max(lo, min(hi, x))


# ─── Veri İndirme ─────────────────────────────────────────────────────────────

def download_all(symbols: list[str], period: str = "90d") -> dict[str, pd.DataFrame]:
    tickers = [f"{s}.IS" for s in symbols] + ["XU100.IS"]
    raw = yf.download(tickers, period=period, auto_adjust=True, progress=False, threads=True)
    data = {}
    for sym in symbols + ["XU100"]:
        ticker = f"{sym}.IS"
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                df = raw.xs(ticker, axis=1, level=1).dropna(how="all")
            else:
                df = raw.dropna(how="all")
            data[sym] = df if len(df) >= 20 else None
        except:
            data[sym] = None
    ok = sum(1 for v in data.values() if v is not None)
    print(f"[Advisor] {ok}/{len(tickers)} hisse indirildi")
    return data


# ─── Skor Hesabı (ham 100p → /10 → 0-10 puan) ───────────────────────────────

def score_stock(sym: str, df: pd.DataFrame, xu100: pd.DataFrame,
                all_returns: dict, sectors: dict) -> dict:
    close = df["Close"]
    vol   = df["Volume"]
    price = float(close.iloc[-1])

    # ── 1. Teknik Analiz (25p) ──────────────────────────────────────────────
    ma20  = float(close.rolling(20).mean().iloc[-1])
    ma50  = float(close.rolling(50).mean().iloc[-1])
    ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else ma50

    ma_score = (3 if price > ma20 else 0) + (3 if ma20 > ma50 else 0) + (2 if ma50 > ma200 else 0)

    rsi = _rsi(close)
    if   40 <= rsi <= 60: rsi_score = 7
    elif 30 <= rsi <  40: rsi_score = 4
    elif 60 <  rsi <= 70: rsi_score = 3
    elif rsi < 30:        rsi_score = 1
    else:                 rsi_score = 0

    macd_val, macd_sig = _macd(close)
    macd_score = (3 if macd_val > macd_sig else 0) + (2 if macd_val > 0 else 0)

    bb_mid, bb_up, bb_lo = _bollinger(close)
    bb_width = (bb_up - bb_lo) / bb_mid if bb_mid else 0
    bb_pos   = (price - bb_lo) / (bb_up - bb_lo) if (bb_up - bb_lo) else 0.5
    bb_score = (3 if bb_pos < 0.35 else (1 if bb_pos < 0.55 else 0)) + (2 if bb_width < 0.05 else 0)

    tech_score = ma_score + rsi_score + macd_score + bb_score  # max 25

    # ── 2. Momentum (20p) ───────────────────────────────────────────────────
    def _ret(n):
        if len(close) < n + 1: return 0.0
        return _pct(float(close.iloc[-1]), float(close.iloc[-n-1]))

    r5, r20, r60 = _ret(5), _ret(20), _ret(60)
    rets5  = [v for v in all_returns["r5"].values()  if v is not None]
    rets20 = [v for v in all_returns["r20"].values() if v is not None]
    rets60 = [v for v in all_returns["r60"].values() if v is not None]

    def _z2p(z, max_p): return _clamp((z + 2) / 4, 0, 1) * max_p

    z5  = _zscore(r5,  rets5)  if rets5  else 0
    z20 = _zscore(r20, rets20) if rets20 else 0
    z60 = _zscore(r60, rets60) if rets60 else 0
    mom_score = _z2p(z5, 5) + _z2p(z20, 7) + _z2p(z60, 8)  # max 20

    # ── 3. Göreli Güç (15p) ─────────────────────────────────────────────────
    rs_score = 0.0
    if xu100 is not None and len(xu100) >= 20:
        xu_ret20 = _pct(float(xu100["Close"].iloc[-1]), float(xu100["Close"].iloc[-20]))
        rs_score += _clamp((r20 - xu_ret20 + 10) / 20, 0, 1) * 10

    sym_sector = next((s for s, m in sectors.items() if sym in m), None)
    if sym_sector:
        sec_rets = sorted([all_returns["r20"].get(m) or 0 for m in sectors[sym_sector]
                           if m in all_returns["r20"]], reverse=True)
        if sec_rets:
            rank    = next((i for i, v in enumerate(sec_rets) if v <= r20), len(sec_rets)) + 1
            top_pct = rank / len(sec_rets)
            rs_score += 5 if top_pct <= 0.20 else (3 if top_pct <= 0.40 else (1 if top_pct <= 0.60 else 0))

    rs_score = min(rs_score, 15)

    # ── 4. Hacim Analizi (15p) ──────────────────────────────────────────────
    vol_vals = vol.dropna()
    vol_5    = float(vol_vals.iloc[-5:].mean())  if len(vol_vals) >= 5  else 0
    vol_20   = float(vol_vals.iloc[-20:].mean()) if len(vol_vals) >= 20 else vol_5
    vol_ratio= vol_5 / vol_20 if vol_20 else 1
    vol_score= _clamp((vol_ratio - 0.5) / 2, 0, 1) * 7
    up_vol   = df[close.diff() > 0]["Volume"].mean() if len(df[close.diff() > 0]) else 0
    dn_vol   = df[close.diff() < 0]["Volume"].mean() if len(df[close.diff() < 0]) else 0
    pv_score = 8 if (up_vol > dn_vol and vol_ratio > 1) else (4 if up_vol > dn_vol else 0)
    volume_score = vol_score + pv_score  # max 15

    # ── 5. Risk & Volatilite (15p) ──────────────────────────────────────────
    atr_val = _atr(df)
    atr_pct = atr_val / price * 100 if price else 0
    atr_score = 7 if 1.5 <= atr_pct <= 5.0 else (4 if 1.0 <= atr_pct < 1.5 else (3 if 5.0 < atr_pct <= 8.0 else 0))

    mdd = _max_drawdown(close, 60)
    mdd_score = 5 if mdd < 0.15 else (2 if mdd < 0.25 else 0)

    if xu100 is not None:
        beta_val = _beta(close.pct_change().dropna(), xu100["Close"].pct_change().dropna())
    else:
        beta_val = 1.0
    beta_score = 3 if 0.7 <= beta_val <= 1.5 else (1 if 0.5 <= beta_val < 0.7 or 1.5 < beta_val <= 2.0 else 0)

    risk_score = atr_score + mdd_score + beta_score  # max 15

    # ── 6. Giriş Zamanlaması (10p) ──────────────────────────────────────────
    sup_lvl  = float(close.iloc[-60:].quantile(0.15)) if len(close) >= 60 else float(close.min())
    dist_sup = _pct(price, sup_lvl)
    sup_score= 5 if 0 <= dist_sup <= 3 else (3 if 0 <= dist_sup <= 7 else (0 if dist_sup < 0 else 1))

    last5    = close.iloc[-5:]
    dip_idx  = last5.idxmin()
    dip_pos  = list(last5.index).index(dip_idx)
    recovery = _pct(float(last5.iloc[-1]), float(last5.min()))
    dip_score= 5 if (dip_pos < 4 and recovery >= 2.0) else (2 if recovery >= 1.0 else 0)

    timing_score = sup_score + dip_score  # max 10

    # ── Toplam (100p) → 10 üzerinden normalize ──────────────────────────────
    raw_total = tech_score + mom_score + rs_score + volume_score + risk_score + timing_score
    total_10  = round(raw_total / 10.0, 1)  # 0–10 arası

    # Zaman dilimi
    if   total_10 >= 7.5 and mom_score >= 14: timeframe = "KISA_VADE"
    elif total_10 >= 6.5:                     timeframe = "ORTA_VADE"
    elif total_10 >= 5.0:                     timeframe = "KISA_VADE"
    else:                                     timeframe = "ÖNERİLMEZ"

    # Stop & Hedef
    stop_loss = round(price * (1 - 0.5 * atr_pct / 100), 4)
    target1   = round(price * (1 + 1.0 * atr_pct / 100), 4)
    target2   = round(price * (1 + 2.0 * atr_pct / 100), 4)

    # Gerekçe
    reasons = []
    if ma_score >= 6:    reasons.append("Güçlü MA dizilimi")
    if mom_score >= 14:  reasons.append("Yüksek momentum")
    if rs_score >= 10:   reasons.append("Endeks üstünde")
    if vol_ratio > 1.3:  reasons.append("Hacim artışı")
    if sup_score >= 4:   reasons.append("Destek yakını")
    if dip_score >= 3:   reasons.append("Dip toparlanması")
    if rsi < 40:         reasons.append("RSI: aşırı satım")
    if bb_pos < 0.35:    reasons.append("Bollinger alt bant")
    reasoning = ", ".join(reasons) if reasons else "Dengeli teknik tablo"

    return {
        "symbol":      sym,
        "price":       round(price, 4),
        "total_score": total_10,
        "scores": {
            "technical":    round(tech_score / 25 * 10, 1),   # 0-10
            "momentum":     round(mom_score  / 20 * 10, 1),
            "rel_strength": round(rs_score   / 15 * 10, 1),
            "volume":       round(volume_score/ 15 * 10, 1),
            "risk":         round(risk_score  / 15 * 10, 1),
            "timing":       round(timing_score/ 10 * 10, 1),
        },
        "timeframe":  timeframe,
        "entry_zone": {"low": round(price * 0.99, 4), "high": round(price * 1.005, 4)},
        "stop_loss":  stop_loss,
        "target1":    target1,
        "target2":    target2,
        "reasoning":  reasoning,
        "rsi":        round(rsi, 1),
        "atr_pct":    round(atr_pct, 2),
        "beta":       round(beta_val, 2),
        "mdd_60":     round(mdd * 100, 1),
        "vol_ratio":  round(vol_ratio, 2),
        "r5":         round(r5, 2),
        "r20":        round(r20, 2),
        "r60":        round(r60, 2),
    }


# ─── Çıkış Sinyali ───────────────────────────────────────────────────────────

def check_exit(active: dict, score_now: dict) -> tuple[str, str]:
    """(sinyal, türkçe_açıklama) döndürür."""
    total = score_now["total_score"]
    rsi   = score_now["rsi"]
    price = score_now["price"]
    stop  = active.get("stop_loss", 0)

    if stop and price < stop:
        return "ACİL_ÇIK", f"Stop seviyesi kırıldı! Fiyat {price:.2f} ₺ < Stop {stop:.2f} ₺"

    if rsi > 75:
        return "ÇIK", f"RSI {rsi:.0f} — aşırı alım bölgesinde, kar al."

    if total < 5.0:
        return "ÇIK", f"Skor {total:.1f}/10 — kritik seviyenin altına düştü."

    if total < 6.5:
        return "DİKKAT", f"Skor {total:.1f}/10 — zayıflıyor, takip et."

    return "DEVAM", ""


# ─── Ana Analiz ──────────────────────────────────────────────────────────────

def run_analysis(dry_run: bool = False, quiet: bool = False) -> dict:
    symbols = CFG["bist100"]
    sectors = CFG["sectors"]
    state   = _load_state()
    capital = state.get("capital", CFG.get("capital", 0))
    active  = state.get("active")

    if not quiet:
        print(f"[Advisor] {len(symbols)} hisse analiz ediliyor...")

    data = download_all(symbols)
    xu100 = data.get("XU100")

    # Getiri hesapla (momentum z-skoru için)
    all_returns = {"r5": {}, "r20": {}, "r60": {}}
    for sym in symbols:
        df = data.get(sym)
        c  = df["Close"] if df is not None else None
        all_returns["r5"][sym]  = _pct(float(c.iloc[-1]), float(c.iloc[-6]))  if (c is not None and len(c) > 5)  else None
        all_returns["r20"][sym] = _pct(float(c.iloc[-1]), float(c.iloc[-21])) if (c is not None and len(c) > 20) else None
        all_returns["r60"][sym] = _pct(float(c.iloc[-1]), float(c.iloc[-61])) if (c is not None and len(c) > 60) else None

    # Skor hesabı
    scores = []
    for sym in symbols:
        df = data.get(sym)
        if df is None: continue
        try:
            scores.append(score_stock(sym, df, xu100, all_returns, sectors))
        except Exception as e:
            print(f"[Advisor] {sym} hata: {e}")

    scores.sort(key=lambda x: x["total_score"], reverse=True)
    eligible = [s for s in scores if s["timeframe"] != "ÖNERİLMEZ"]
    top_picks = [{**s, "rank": i+1} for i, s in enumerate(eligible[:3])]

    # Aktif pozisyon çıkış kontrolü
    exit_signal = {"symbol": None, "signal": "—", "score_now": 0.0, "score_prev": 0.0, "message": ""}
    new_pick_for_exit = None

    if active:
        sym = active["symbol"]
        active_score_data = next((s for s in scores if s["symbol"] == sym), None)
        if active_score_data:
            signal, msg = check_exit(active, active_score_data)
            exit_signal = {
                "symbol":     sym,
                "signal":     signal,
                "score_now":  active_score_data["total_score"],
                "score_prev": active.get("last_score", active_score_data["total_score"]),
                "message":    msg,
            }
            alts = [s for s in eligible if s["symbol"] != sym]
            if alts:
                new_pick_for_exit = alts[0]

    # Lot hesapları (önerilen hisseler için)
    lot_info = {}
    if capital > 0:
        # Mevcut pozisyon varsa önce satış sermayesi hesapla
        avail_capital = capital
        if active:
            qty  = active.get("qty", 0)
            price_now = scores[0]["price"] if scores else 0
            # Aktif sembolün güncel fiyatını bul
            act_score = next((s for s in scores if s["symbol"] == active["symbol"]), None)
            if act_score and qty > 0:
                avail_capital = calc_capital_after_sell(qty, act_score["price"])

        for p in top_picks:
            lots = calc_lots(avail_capital, p["price"])
            lot_info[p["symbol"]] = {
                "lots": lots,
                "price": p["price"],
                "cost": round(lots * p["price"] * (1 + CFG["commission_rate"]), 2),
            }

    # Tracker P&L
    try:
        from tracker import track
        tracker_data = track(state)
    except Exception as e:
        tracker_data = {"error": str(e)}

    ts = time.time()
    result = {
        "ts":          ts,
        "ts_str":      _ts_str(ts),
        "capital":     capital,
        "top_picks":   top_picks,
        "exit_signal": exit_signal,
        "lot_info":    lot_info,
        "tracker":     tracker_data,
        "score_table": {s["symbol"]: {"total": s["total_score"], "rank": i+1,
                                       "timeframe": s["timeframe"]}
                        for i, s in enumerate(scores)},
    }

    if not dry_run:
        RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if not quiet:
            print(f"[Advisor] Sonuç yazıldı: {RESULT_PATH}")

        # Firebase'e yaz (telefon erişimi için)
        _firebase_push(result)

        # State güncelle
        if active and exit_signal["signal"] != "—":
            state["active"]["last_score"] = exit_signal["score_now"]
            _save_state(state)

        # Push bildirimleri
        try:
            import notifier
            if exit_signal["signal"] in ("DİKKAT", "ÇIK", "ACİL_ÇIK"):
                notifier.send_exit_signal(
                    signal=exit_signal["signal"],
                    symbol=exit_signal["symbol"],
                    score_prev=exit_signal["score_prev"],
                    score_now=exit_signal["score_now"],
                    message=exit_signal["message"],
                    new_pick=new_pick_for_exit,
                    lot_info=lot_info,
                )
            elif top_picks and not active:
                # Aktif pozisyon yoksa günlük öneriyi bildir
                notifier.send_daily_pick(top_picks[0], lot_info.get(top_picks[0]["symbol"]))
        except Exception as e:
            print(f"[Advisor] Push hatası: {e}")

    return result


# ─── Tek Hisse Detay ─────────────────────────────────────────────────────────

def run_single(symbol: str):
    print(f"[Advisor] {symbol} analiz ediliyor...")
    data  = download_all([symbol])
    xu100 = data.get("XU100")
    df    = data.get(symbol)
    if df is None:
        print(f"Hata: {symbol} için veri alınamadı."); return
    all_returns = {
        "r5":  {symbol: _pct(float(df["Close"].iloc[-1]), float(df["Close"].iloc[-6]))},
        "r20": {symbol: _pct(float(df["Close"].iloc[-1]), float(df["Close"].iloc[-21]))},
        "r60": {symbol: _pct(float(df["Close"].iloc[-1]), float(df["Close"].iloc[-61]))},
    }
    s = score_stock(symbol, df, xu100, all_returns, CFG["sectors"])
    print(json.dumps(s, ensure_ascii=False, indent=2))


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BIST100 Sermaye Danışmanı")
    parser.add_argument("--run",    action="store_true")
    parser.add_argument("--test",   action="store_true")
    parser.add_argument("--check",  action="store_true")
    parser.add_argument("--quiet",  action="store_true")
    parser.add_argument("--symbol", type=str)
    args = parser.parse_args()

    if args.symbol:
        run_single(args.symbol.upper()); return

    if args.check:
        state  = _load_state()
        active = state.get("active")
        if not active:
            print("[Advisor] Aktif pozisyon yok."); return
        sym  = active["symbol"]
        data = download_all([sym])
        df   = data.get(sym)
        if df is None:
            print(f"[Advisor] {sym} veri alınamadı."); return
        all_returns = {"r5": {sym: 0}, "r20": {sym: 0}, "r60": {sym: 0}}
        score  = score_stock(sym, df, data.get("XU100"), all_returns, CFG["sectors"])
        signal, msg = check_exit(active, score)
        print(f"\n[{sym}] Skor: {score['total_score']:.1f}/10 | RSI: {score['rsi']:.0f} | Sinyal: {signal}")
        if msg: print(f"Mesaj: {msg}")

        # Çıkış sinyalinde push gönder
        if signal in ("DİKKAT", "ÇIK", "ACİL_ÇIK"):
            try:
                import notifier
                notifier.send_exit_signal(signal, sym, active.get("last_score", score["total_score"]),
                                          score["total_score"], msg, None, {})
            except: pass
        return

    if args.run:
        result = run_analysis(dry_run=False, quiet=args.quiet)
    elif args.test:
        result = run_analysis(dry_run=True,  quiet=args.quiet)
    else:
        print("Kullanım: advisor.py --run | --test | --check | --symbol SEMBOL"); sys.exit(1)

    print("\n" + "="*55)
    print(f"Analiz: {result['ts_str']}  |  Sermaye: {result['capital']:,.0f} TL")
    print(f"Top 3:")
    for p in result["top_picks"]:
        li = result["lot_info"].get(p["symbol"])
        lot_str = f"({li['lots']:,} lot)" if li else ""
        print(f"  {p['rank']}. {p['symbol']:8s} {p['total_score']:.1f}/10 | {p['timeframe']} {lot_str}")
        print(f"     {p['reasoning']}")
    es = result["exit_signal"]
    if es["symbol"]:
        print(f"\n[{es['symbol']}] Sinyal: {es['signal']}  Skor: {es['score_now']:.1f}/10")
        if es["message"]: print(f"  > {es['message']}")


if __name__ == "__main__":
    main()
