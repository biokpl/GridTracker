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
from datetime import datetime, timedelta
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

# Strateji modu (config.json'dan, varsayılan RK):
#   "RK"     → R/K-ODAKLI (ÖNERİLEN): hedef DAİMA riskten büyük (reward ≥ 1.4×risk),
#              sakin hisse tercihi (ATR %1.5-2.2), R/K<1.2 olanı önermez. "Riske değer kâr."
#   "HIBRIT" → eskinin ~%3 hedefi, geniş stop (R/K<1 olabilir), yüksek isabete dayalı
#   "GUNLUK" → çok sıkı stop (~%1.2), küçük hedef (~%2.2)
#   "ORTA"   → orijinal orta vade: geniş ATR hedef, geniş stop
STRATEGY_MODE = (CFG.get("strategy_mode") or "RK").upper()
def _is_daily() -> bool:
    return STRATEGY_MODE.startswith("G")    # GUNLUK / GÜNLÜK
def _is_hybrid() -> bool:
    return STRATEGY_MODE.startswith("H")    # HIBRIT / HİBRİT
def _is_rk() -> bool:
    return STRATEGY_MODE.startswith("R") or STRATEGY_MODE.startswith("V")  # RK / VURKAC


def _firebase_push(result: dict):
    """Özet veriyi Firebase'e yazar (telefon erişimi için)."""
    import requests as _req

    # Firebase'e gönderilecek özet (score_table hariç — çok büyük)
    payload = {
        "ts":          result["ts"],
        "ts_str":      result["ts_str"],
        "capital":     result["capital"],
        "top_picks":   result["top_picks"],
        "active_pick": result.get("active_pick"),
        "exit_signal": result["exit_signal"],
        "lot_info":    result["lot_info"],
        "tracker":     result["tracker"],
        # Bekleme günü bayrağı + piyasa rejimi — web/mobil kartında "BUGÜN
        # BEKLEME GÜNÜ" uyarısı bunlara bakıyor (Firebase'e yazılmazsa web'de
        # uyarı çıkmıyordu).
        "no_trade_today": bool(result.get("no_trade_today")),
        "regime":         result.get("regime"),
        "regime_msg":     result.get("regime_msg"),
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


def _record_recommendation(state: dict, symbol: str, pick: dict = None):
    """
    Gün içinde önerilen sembolleri kaydeder. Akşam senkronunda bu sembollerin
    HEPSİ 1.xlsx'te aranır; al-sat yapılmışsa kârı history'ye işlenir.
    Böylece TTKOM→AKSA gibi gün içi geçişlerde tüm öneriler takip edilir.
    """
    if not symbol:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    # Son 7 günün önerilerini tut — kullanıcı bir gün sonra (ertesi sabah) alabilir;
    # "sadece bugün" filtresi dünkü öneriyi düşürüp alımı görünmez yapıyordu.
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recs = state.setdefault("recommended_today", [])
    recs[:] = [r for r in recs if isinstance(r, dict) and r.get("date", "") >= cutoff]
    if any(r.get("symbol") == symbol for r in recs):
        return
    entry = {"symbol": symbol, "date": today, "entry_date": today}
    if pick:
        entry.update({
            "stop_loss": pick.get("stop_loss", 0),
            "hard_stop": pick.get("hard_stop", 0),
            "target1":   pick.get("target1", 0),
            "target2":   pick.get("target2", 0),
            "timeframe": pick.get("timeframe", ""),
            "score":     pick.get("total_score", 0),
        })
    recs.append(entry)


def _ts_str(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


def _pct(a, b) -> float:
    return (a - b) / b * 100 if b else 0.0


def calc_lots(capital: float, price: float, commission_rate: float = 0.0001) -> int:
    """Sermaye ve fiyatla alınabilecek lot sayısı (komisyon dahil).
    NaN/geçersiz girdide 0 döner (bozuk veri tüm analizi kırmasın)."""
    try:
        if (price != price) or (capital != capital):   # NaN kontrolü
            return 0
        if price <= 0 or capital <= 0:
            return 0
        return int(capital / (price * (1 + commission_rate)))
    except (TypeError, ValueError):
        return 0


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

def _weekly_trend(sym: str) -> tuple[str, float]:
    """
    Haftalık grafik trendi: MA20 eğimi (8 hafta).
    Dönür: ('yukari'|'yatay'|'asagi', egim_pct)
    Günlük iyi görünen ama haftalık düşüşte olan hisseyi filtreler.
    """
    try:
        df = yf.Ticker(f"{sym}.IS").history(period="52wk", interval="1wk", auto_adjust=True)
        if df is None or len(df) < 10:
            return "yatay", 0.0
        c = df["Close"].dropna()
        ma = c.rolling(20, min_periods=8).mean()
        if len(ma.dropna()) < 2:
            return "yatay", 0.0
        now  = float(ma.iloc[-1])
        prev = float(ma.iloc[-8]) if len(ma) >= 8 else float(ma.iloc[0])
        slope = (now - prev) / prev * 100 if prev else 0.0
        if slope > 2.5:  return "yukari", round(slope, 1)
        if slope < -2.5: return "asagi",  round(slope, 1)
        return "yatay", round(slope, 1)
    except Exception:
        return "yatay", 0.0


def _event_risk(sym: str, df: pd.DataFrame) -> tuple[float, str]:
    """
    Bilanço / temettü / olay riski skoru (entry_bonus'a eklenir):
      - BIST bilanço dönemleri: Mar/May/Aug/Nov ortaları ±10 gün → belirsizlik
      - yfinance calendar: temettü tarihi yakınsa +bonus (katalizör)
      - Ani fiyat+hacim anomalisi: geçen 3 günde sırışık büyük hareket → haber var
    Döner: (skor_ayarlamasi, etiket)
    """
    adj, tag = 0.0, ""
    now = datetime.now()
    # 1) Bilanço dönem riski (yön belirsiz = ceza)
    BILANÇO_AYLAR = {3: 15, 5: 15, 8: 15, 11: 15}   # ay → gün (ortası)
    if now.month in BILANÇO_AYLAR:
        gun = BILANÇO_AYLAR[now.month]
        kalan = abs(now.day - gun)
        if kalan <= 10:
            adj -= 1.5
            tag = f"bilanço-yakın({kalan}g)"
    # 2) yfinance temettü takvimi: yakın temettü = fiyat katalizörü
    try:
        cal = yf.Ticker(f"{sym}.IS").calendar
        ex_div = cal.get("Ex-Dividend Date") if isinstance(cal, dict) else None
        if ex_div and hasattr(ex_div, "toordinal"):
            kalan_div = (ex_div - now.date()).days
            if 0 <= kalan_div <= 20:
                adj += 1.5; tag = f"temettü-yakın({kalan_div}g)"
            elif 20 < kalan_div <= 45:
                adj += 0.5; tag = f"temettü-gelecek({kalan_div}g)"
    except Exception:
        pass
    # 3) Fiyat+hacim anomalisi son 3 günde: muhtemelen büyük haber var
    try:
        c = df["Close"]; v = df["Volume"]
        c3 = c.iloc[-3:].pct_change().abs().dropna()
        v3 = v.iloc[-3:]
        v20 = float(v.iloc[-20:].mean()) if len(v) >= 20 else 1
        if len(c3) and len(v3):
            max_move = float(c3.max()) * 100
            max_vol  = float(v3.max()) / v20 if v20 else 1
            if max_move > 4.0 and max_vol > 2.5:
                adj -= 1.0; tag += (" " if tag else "") + "haber-anomali"
    except Exception:
        pass
    return round(adj, 2), tag


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
    if _is_daily():
        # GÜNLÜK: sıkı (~%1) stop ancak ORTA oynaklıkta yaşar. Çok vahşi hisse
        # (ATR>%3.5) fitil avına takılır → elenir; çok sakin (ATR<%1) %1.5 hedefe
        # ulaşamaz → düşük puan. İdeal bant %1.2–2.8.
        atr_score = (7 if 1.2 <= atr_pct <= 2.8 else
                     5 if 2.8 < atr_pct <= 3.5 else
                     3 if 0.9 <= atr_pct < 1.2 else
                     1 if 3.5 < atr_pct <= 4.5 else 0)
    elif _is_rk():
        # R/K-ODAKLI: SAKİN hisse tercih (ATR %1.5–2.2). Bu bantta dar stop hem
        # güvenli (fitile takılmaz) hem hedef ulaşılabilir → R/K doğal olarak ≥1.4.
        # Oynak hisse (>%2.8) ya uzak hedef gerektirir ya R/K bozar → ağır ceza.
        atr_score = (7 if 1.4 <= atr_pct <= 2.2 else
                     5 if 2.2 < atr_pct <= 2.8 else
                     4 if 1.0 <= atr_pct < 1.4 else
                     2 if 2.8 < atr_pct <= 3.5 else 0)
    elif _is_hybrid():
        # HİBRİT: orta oynaklık tercih (R/K doğal olarak iyi). Aşırı oynak (>%5)
        # hisse geniş stop gerektirir → R/K bozulur → ceza. İdeal bant %1.5–3.5.
        atr_score = (7 if 1.5 <= atr_pct <= 3.5 else
                     5 if 3.5 < atr_pct <= 5.0 else
                     4 if 1.0 <= atr_pct < 1.5 else
                     2 if 5.0 < atr_pct <= 6.5 else 0)
    else:
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
    if _is_daily():
        timeframe = "GÜNLÜK" if total_10 >= 5.0 else "ÖNERİLMEZ"
    elif total_10 >= 7.5 and mom_score >= 14: timeframe = "KISA_VADE"
    elif total_10 >= 6.5:                     timeframe = "ORTA_VADE"
    elif total_10 >= 5.0:                     timeframe = "KISA_VADE"
    else:                                     timeframe = "ÖNERİLMEZ"

    # ── Stop & Hedef ──────────────────────────────────────────────────────
    # Yapısal direnç (her iki modda hedef kapağı için): fiyatın üstündeki en
    # yakın anlamlı tepe (20 & 55 gün).
    _highs = []
    if len(close) >= 20: _highs.append(float(close.iloc[-20:].max()))
    if len(close) >= 55: _highs.append(float(close.iloc[-55:].max()))
    _res_above   = sorted(h for h in _highs if h > price * 1.005)
    _nearest_res = _res_above[0] if _res_above else None

    if _is_daily():
        # ══ GÜNLÜK MOD: sıkı stop (~%1), ulaşılabilir hedef (min %1.5, R/K≥1.8) ══
        # Stop: yakın swing dibi (son 5 gün) VEYA yüzde tabanlı — %0.8–1.5 bandında.
        _swing_low = float(close.iloc[-5:].min()) if len(close) >= 5 else float(close.min())
        _struct    = _swing_low - 0.15 * atr_val
        _stop_far  = price * (1 - 0.012)            # en geniş: %1.2 (kullanıcı tercihi ~%1)
        _stop_near = price * (1 - 0.008)            # en dar:   %0.8
        stop_loss  = round(min(max(_struct, _stop_far), _stop_near), 4)
        hard_stop  = round(stop_loss - 0.5 * atr_val, 4)   # felaket: stop'un 0.5 ATR altı
        _risk_pct  = (price - stop_loss) / price if price else 0.01
        # Hedef: max(%1.5, riskin 1.8 katı) — "anlamlı + riske değer". ~%3 tavan
        # (günlük ulaşılabilirlik). Sonra dirençte kapanır.
        _tgt_pct = min(max(0.015, 1.8 * _risk_pct), 0.03)
        target1  = price * (1 + _tgt_pct)
        if _nearest_res is not None and _nearest_res < target1:
            target1 = max(price * 1.008, _nearest_res - 0.10 * atr_val)
        target1 = round(target1, 4)
        # target2: ikinci kademe (hedefin ~1.6 katı mesafe), ATR×2 veya direnç tavanı
        target2 = round(min(price * (1 + 2 * _tgt_pct),
                            target1 + max(0.008 * price, 0.7 * atr_val)), 4)
        if target1 <= price:   target1 = round(price * 1.012, 4)
        if target2 <= target1: target2 = round(target1 * 1.01, 4)
    elif _is_rk():
        # ══ R/K-ODAKLI: hedef DAİMA riskten büyük (reward ≥ 1.4 × risk) + ulaşılabilir ══
        # Stop: yapısal swing dibi (son 10 gün), 1.0–1.3 ATR bandı (sakin hissede ~%1.5-2.2).
        _swing_low = float(close.iloc[-10:].min()) if len(close) >= 10 else float(close.min())
        _struct    = _swing_low - 0.2 * atr_val
        _near      = price - 1.0 * atr_val          # en dar
        _far       = price - 1.3 * atr_val          # en geniş
        stop_loss  = round(min(max(_struct, _far), _near), 4)
        hard_stop  = round(stop_loss - 0.6 * atr_val, 4)
        _risk      = price - stop_loss
        # Hedef = riskin 1.4 katı (reward > risk GARANTİ), taban %1.5,
        # ULAŞILABİLİRLİK TAVANI ~%3.5 (günde-iki günde dönebilsin).
        target1 = price + max(1.4 * _risk, price * 0.015)
        target1 = min(target1, price * 1.05)   # tavan %5 (eski %3.5 fazla dardı:
        # oynak hisselerde R/K<1.2 kalıp HEPSİ ÖNERİLMEZ oluyordu → günlerce işlem yok)
        # Dirençte kapat (takılmadan önce sat)
        if _nearest_res is not None and _nearest_res < target1:
            target1 = max(price * 1.008, _nearest_res - 0.10 * atr_val)
        target1 = round(target1, 4)
        # target2: riskin ~2 katı, ~%7 tavan
        target2 = round(min(price + 2.0 * _risk, price * 1.07), 4)
        if target1 <= price:   target1 = round(price * 1.012, 4)
        if target2 <= target1: target2 = round(target1 * 1.012, 4)
        # NOT: Oynak hisselerde stop büyük → 1.4×risk hedef %3.5 tavanı aşar →
        # tavana çekilince R/K<1.2 kalır → R/K kapısı bu hisseleri ELER.
        # Böylece sistem doğal olarak SAKİN hisseleri seçer (risk küçük, R/K iyi).
    else:
        # ══ HİBRİT / ORTA MOD: geniş ATR hedef (~%3, dirençte kapanır) ══
        # Stop: YAKIN swing dibi (son 10 gün) + küçük ATR tamponu.
        #   HİBRİT → 1.0–1.5 ATR (biraz sıkı, R/K iyileşir, isabet korunur)
        #   ORTA   → 1.0–1.8 ATR (tam genişlik, en yüksek nefes alanı)
        _swing_low   = float(close.iloc[-10:].min()) if len(close) >= 10 else float(close.min())
        _struct_stop = _swing_low - 0.3 * atr_val
        _near_stop   = price - 1.0 * atr_val
        _far_stop    = price - (1.5 if _is_hybrid() else 1.8) * atr_val
        stop_loss    = round(min(max(_struct_stop, _far_stop), _near_stop), 4)
        hard_stop    = round(stop_loss - 0.8 * atr_val, 4)
        _atr_t1 = price * (1 + 1.0 * atr_pct / 100)
        _atr_t2 = price * (1 + 2.0 * atr_pct / 100)
        if _nearest_res is not None and _nearest_res < _atr_t1:
            target1 = round(max(price * 1.005, _nearest_res - 0.15 * atr_val), 4)
        else:
            target1 = round(_atr_t1, 4)
        target2 = round(max(_atr_t2, target1 + 1.0 * atr_val), 4)
        if target1 <= price:   target1 = round(price * 1.01, 4)
        if target2 <= target1: target2 = round(target1 * 1.01, 4)

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

    # ── Giriş Kalitesi Skoru (ÇIK sonrası geçiş için) ──────────────────────
    # Yüksek total_score ama kötü giriş noktası → ceza
    # Düşük r5 + RSI ısınma bölgesi + destek yakını → bonus
    entry_bonus = 0.0

    # RSI ısınma bölgesi (40-58): en ideal giriş — ne soğuk ne sıcak
    if   40 <= rsi <= 58:  entry_bonus += 1.5
    elif 35 <= rsi < 40:   entry_bonus += 0.5   # biraz soğuk ama toparlanabilir
    elif 58 < rsi <= 65:   entry_bonus += 0.0
    elif rsi > 70:         entry_bonus -= 2.0   # zaten pompalanmış
    elif rsi < 30:         entry_bonus -= 0.5   # aşırı satım = hâlâ düşüyor olabilir

    # Bollinger konumu: alt banda yakın = erken giriş; üst bant ÜSTÜ = tehlike
    if   bb_pos > 1.00:    entry_bonus -= 3.0   # ÜST BANDIN ÜSTÜ — aşırı gergin, tepe riski
    elif bb_pos > 0.85:    entry_bonus -= 2.0   # üst banda çok yakın
    elif bb_pos > 0.70:    entry_bonus -= 1.0   # üst yarı
    elif bb_pos < 0.30:    entry_bonus += 1.5   # alt banda yakın = fırsat
    elif bb_pos < 0.45:    entry_bonus += 0.8

    # 5 günlük hareket: hafif pozitif ideal, zaten fırlamamış
    if   1.0 <= r5 <= 4.0: entry_bonus += 1.0   # başlıyor
    elif r5 > 6.0:         entry_bonus -= 2.0   # zaten fırlamış
    elif r5 < -3.0:        entry_bonus -= 1.0   # düşüyor

    # UZUN/ORTA VADELİ AŞIRI YÜKSELİŞ — "tepe" riski (önceden hiç bakılmıyordu!)
    # Hisse zaten çok yükselmişse yeni giriş riskli (düzeltme ihtimali yüksek)
    if   r60 > 60: entry_bonus -= 2.5   # 60 günde %60+ → aşırı, tepe riski
    elif r60 > 40: entry_bonus -= 1.5
    elif r60 > 25: entry_bonus -= 0.5
    if   r20 > 25: entry_bonus -= 1.5   # 20 günde %25+ → kısa vadede fazla ısınmış
    elif r20 > 15: entry_bonus -= 0.8

    # HACİMSİZ YÜKSELİŞ — kırılgan (yükseliş hacimle desteklenmiyorsa güvenilmez)
    if vol_ratio < 0.70 and r5 > 3.0:
        entry_bonus -= 1.5   # fiyat çıkıyor ama hacim eriyor → sürdürülemez

    # Risk/Kazanç oranı: (H1-fiyat) / (fiyat-stop)
    rr_ratio = 0.0
    if stop_loss < price and target1 > price:
        rr_ratio = (target1 - price) / (price - stop_loss)
        if   rr_ratio >= 3.0: entry_bonus += 1.5
        elif rr_ratio >= 2.0: entry_bonus += 1.0
        elif rr_ratio >= 1.5: entry_bonus += 0.0
        else:                 entry_bonus -= 1.5   # kazanç potansiyeli düşük

    # R/K KAPISI (mod bazlı):
    #   GÜNLÜK → R/K<1.5 ise ele (komik kâr için işlem açma; sıkı stop ⇒ yüksek R/K mümkün)
    #   HİBRİT → R/K<0.7 ise ele (sadece BERBAT olanları; yüksek isabeti veren
    #            geniş-stop/kenar vakaları korunur — eski sistemin gücü buydu)
    if timeframe != "ÖNERİLMEZ":
        if _is_daily() and rr_ratio < 1.5:
            timeframe = "ÖNERİLMEZ"
        elif _is_rk() and 0 < rr_ratio < 1.0:
            # R/K-ODAKLI (günlük-aktif kalibrasyon 2026-06-22): reward en az risk
            # kadar olsun (rr≥1.0). 1.2 eşiği mevcut oynak piyasada güçlü hisseleri
            # de eliyordu; 1.0 ödül≥risk ilkesini korur ama havuzu makul genişletir.
            # (rr<1.0 = riske değmez: kaybedersen kazancından fazla kaybedersin.)
            timeframe = "ÖNERİLMEZ"
        elif _is_hybrid() and 0 < rr_ratio < 0.5:
            # Sadece BERBAT R/K (risk, kârın 2 katından fazla). İyi-isabetli
            # geniş-stop vakaları korunur; R/K disiplini esas olarak entry_bonus
            # (skor sıralaması) + ATR tercihi ile sağlanır.
            timeframe = "ÖNERİLMEZ"

    # ── NEGATİF IRAKSAMA (dağıtım işareti) ─────────────────────────────────
    # Endeks GÜÇLÜ artarken (≥+1%) hisse DÜŞÜYORSA büyük para o hisseden
    # çıkıyor demektir — ertesi gün(ler) genelde zayıf. TEMKİNLİ doz: sert
    # eleme değil, sıralamada geri iten ceza (dar tetik, yanlış pozitif az).
    _neg_div = False
    if xu100 is not None and len(xu100) > 1 and len(close) > 1:
        try:
            _xu_r1 = _pct(float(xu100["Close"].iloc[-1]), float(xu100["Close"].iloc[-2]))
            _st_r1 = _pct(price, float(close.iloc[-2]))
            if _xu_r1 >= 1.0 and _st_r1 <= -0.3:
                entry_bonus -= 2.0
                _neg_div = True
        except Exception:
            pass

    # ── HAFTALIK TREND FİLTRESİ ────────────────────────────────────────────
    # Günlük iyi, haftalık aşağı = büyük para karşı → güçlü ceza
    w_trend, w_slope = _weekly_trend(sym)
    if   w_trend == "asagi":  entry_bonus -= 2.5   # haftalık MA20 aşağı → kurumlar satıyor
    elif w_trend == "yukari": entry_bonus += 0.5   # rüzgar arkada

    # ── OLAY RİSKİ (bilanço/temettü/anomali) ────────────────────────────────
    evt_adj, evt_tag = _event_risk(sym, df)
    entry_bonus += evt_adj

    # Giriş skoru = toplam skor + giriş bonusu (max 10 ile sınırla)
    entry_score = round(min(10.0, max(0.0, total_10 + entry_bonus)), 1)

    # Gerekçeye haftalık trend + olay bilgisi ekle
    if w_trend == "asagi":  reasoning += f", Haftalık trend aşağı ({w_slope:+.1f}%)"
    elif w_trend == "yukari": reasoning += f", Haftalık trend yukarı ({w_slope:+.1f}%)"
    if evt_tag: reasoning += f", {evt_tag}"
    if _neg_div: reasoning += ", ⚠ Negatif ıraksama (endeks artarken düştü)"

    return {
        "symbol":       sym,
        "price":        round(price, 4),
        "total_score":  total_10,
        "entry_score":  entry_score,   # ÇIK sonrası geçiş için giriş kalitesi
        "rr_ratio":     round(rr_ratio, 2),
        "scores": {
            "technical":    round(tech_score / 25 * 10, 1),
            "momentum":     round(mom_score  / 20 * 10, 1),
            "rel_strength": round(rs_score   / 15 * 10, 1),
            "volume":       round(volume_score/ 15 * 10, 1),
            "risk":         round(risk_score  / 15 * 10, 1),
            "timing":       round(timing_score/ 10 * 10, 1),
        },
        "timeframe":  timeframe,
        "entry_zone": {"low": round(price * 0.99, 4), "high": round(price * 1.005, 4)},
        "stop_loss":  stop_loss,
        "hard_stop":  hard_stop,
        "target1":    target1,
        "target2":    target2,
        "reasoning":  reasoning,
        "rsi":        round(rsi, 1),
        "bb_pos":     round(bb_pos, 3),
        "atr_pct":    round(atr_pct, 2),
        "beta":       round(beta_val, 2),
        "mdd_60":     round(mdd * 100, 1),
        "vol_ratio":  round(vol_ratio, 2),
        "r5":         round(r5, 2),
        "r20":        round(r20, 2),
        "r60":        round(r60, 2),
    }


# ─── Çıkış Sinyali (Çok Katmanlı Puanlama) ──────────────────────────────────

def check_exit(active: dict, score_now: dict) -> tuple[str, str, int]:
    """
    Çoklu sinyal harmanlayarak çıkış kararı verir.
    Her sinyal puanlanır → toplam puan eşiği geçince ÇIK.

    Döndürür: (sinyal, açıklama, çıkış_puanı)
    Sinyaller: DEVAM | DİKKAT | ÇIK | ACİL_ÇIK
    """
    price     = score_now["price"]
    rsi       = score_now["rsi"]
    total     = score_now["total_score"]
    bb_pos    = score_now.get("bb_pos", 0.5)
    vol_ratio = score_now.get("vol_ratio", 1.0)
    r5        = score_now.get("r5", 0.0)

    stop  = active.get("stop_loss", 0)
    h1    = active.get("target1", 0)
    h2    = active.get("target2", 0)
    entry = active.get("entry_price", 0)

    # ── ACİL: Stop Loss kırıldı (puan sistemini atla) ─────────────────────
    if stop and price < stop:
        return "ACİL_ÇIK", f"Stop kırıldı! {price:.2f} < {stop:.2f} ₺", 10

    exit_pts = 0
    signals  = []

    # ── 1. HEDEF FİYAT (3p / 4p) ─────────────────────────────────────────
    if h2 and price >= h2:
        exit_pts += 4
        gain_pct = _pct(price, entry) if entry else 0
        signals.append(f"2. Hedef aşıldı ({price:.2f} ₺, %+{gain_pct:.1f})")
    elif h1 and price >= h1:
        exit_pts += 3
        gain_pct = _pct(price, entry) if entry else 0
        signals.append(f"1. Hedef aşıldı ({price:.2f} ₺, %+{gain_pct:.1f})")

    # ── 2. RSI AŞIRI ALIM (2p / 3p) ──────────────────────────────────────
    if rsi >= 78:
        exit_pts += 3
        signals.append(f"RSI {rsi:.0f} (aşırı alım bölgesi)")
    elif rsi >= 72:
        exit_pts += 2
        signals.append(f"RSI {rsi:.0f} (yükselmiş)")

    # ── 3. BOLLİNGER ÜST BANT (1p / 2p) ──────────────────────────────────
    if bb_pos >= 0.90:
        exit_pts += 2
        signals.append("Bollinger üst bandın üzerinde")
    elif bb_pos >= 0.80:
        exit_pts += 1
        signals.append("Bollinger üst banda yakın")

    # ── 4. MOMENTUM UYUŞMAZLIĞI (2p) ──────────────────────────────────────
    # Fiyat 5 günde %4+ çıktı ama RSI hâlâ zayıf → kırılgan yükseliş
    if r5 >= 4.0 and rsi < 58:
        exit_pts += 2
        signals.append(f"Fiyat %{r5:.1f} yükseldi ama RSI zayıf")

    # ── 5. HACİM AZALIYOR (1p) ────────────────────────────────────────────
    # Fiyat giriş üzerindeyken hacim erimesi → ilgi kaybı
    if entry and price > entry and vol_ratio < 0.70:
        exit_pts += 1
        signals.append("Hacim zayıflıyor")

    # ── 6. SKOR DÜŞÜŞÜ (2p / 3p) ─────────────────────────────────────────
    # NOT: Öneri barı total≥5.0; bu yüzden çıkış uyarısı da total<5.0'da başlar.
    # (Eskiden total<6.5→+2 idi; total 5-6.5 önerilen hisse ALIR ALMAZ "skor
    # zayıf" puanı alıp DİKKAT veriyordu — öneri/çıkış çelişkisi giderildi.)
    if total < 4.0:
        exit_pts += 3
        signals.append(f"Teknik skor {total:.1f}/10")
    elif total < 5.0:
        exit_pts += 2
        signals.append(f"Skor zayıflıyor ({total:.1f}/10)")

    # ── KARAR ─────────────────────────────────────────────────────────────
    msg = " | ".join(signals)

    if exit_pts >= 5:
        return "ÇIK", msg, exit_pts
    elif exit_pts >= 3:
        return "DİKKAT", msg, exit_pts
    else:
        return "DEVAM", "", exit_pts


# ─── Erken Zayıflama / Bozulma Dedektörü (AŞAĞI yönlü) ───────────────────────

def check_early_weakness(active: dict, df: pd.DataFrame, score: dict,
                         xu100: pd.DataFrame = None,
                         intraday_chg: float = None) -> tuple[str, str, int]:
    """
    check_exit yukarı/kâr-al odaklıdır; bu fonksiyon DÜŞÜŞ/kırılma odaklıdır.
    Açık pozisyonda erken bozulma belirtilerini stop'a varmadan yakalar →
    vur-kaç: küçük zararla (veya küçük kârla) erkenden çık, sıradakine geç.

    Döndürür: (level, mesaj, puan)
    level: DEVAM | ZAYIFLAMA (hazır ol) | ERKEN_ÇIK (stop'a varmadan çık)
    Dengeli eşik: puan ≥ 5 → ERKEN_ÇIK, ≥ 3 → ZAYIFLAMA
    """
    close = df["Close"]
    price = float(score.get("price") or close.iloc[-1])
    entry = active.get("entry_price", 0) or 0
    stop  = active.get("stop_loss", 0) or 0
    rsi   = score.get("rsi", 50.0)

    loss_pct = ((price - entry) / entry * 100) if entry else 0.0

    pts = 0
    sig = []

    # YUMUŞAK SİNYAL KAPISI: Erken zayıflama = pozisyon ALEYHE dönüyor demektir.
    # Desteğe yakın / dip-toparlanması ile alınan hisse TANIMI GEREĞİ MA altında ve
    # RSI'si soğumuştur (pullback budur — iyi giriş). Pozisyon henüz flat/yeşilken
    # bu yumuşak momentum sinyalleri (MA/MACD/RSI) zayıflık SAYILMAZ; yoksa yeni
    # alınan her hisse anında DİKKAT verir (öneri mantığıyla çelişir).
    # Sadece pozisyon en az %0.5 zarardayken bu sinyaller devreye girer.
    _losing = loss_pct <= -0.5

    # 1) Kısa vade trend kırıldı — fiyat MA9 / MA20 altında (yalnız zararda)
    ma9  = float(close.rolling(9).mean().iloc[-1])  if len(close) >= 9  else price
    ma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else price
    if _losing and price < ma9:  pts += 1; sig.append("MA9 altı")
    if _losing and price < ma20: pts += 1; sig.append("MA20 altı")

    # 2) MACD aşağı — taze aşağı kesişim ekstra ağırlık (yalnız zararda)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    sgl   = macd.ewm(span=9, adjust=False).mean()
    if _losing and len(macd) >= 2:
        m_now, m_prv = float(macd.iloc[-1]), float(macd.iloc[-2])
        s_now, s_prv = float(sgl.iloc[-1]),  float(sgl.iloc[-2])
        if m_now < s_now:
            pts += 1; sig.append("MACD aşağı")
            if m_prv >= s_prv:
                pts += 1; sig.append("MACD taze aşağı kesişim")

    # 3) Son 5 günün dibi kırıldı — destek bozulması (yalnız ZARARDA; aksi halde
    #    desteğe yakın alınan taze pozisyon alır almaz ZAYIFLAMA verir — kullanıcı
    #    şikayeti: BIMAS aldı, anında "5-gün dibi kırıldı | Endeksten zayıf" DİKKAT.)
    if _losing and len(close) >= 6:
        low5 = float(close.iloc[-6:-1].min())
        if price < low5:
            pts += 2; sig.append("5-gün dibi kırıldı")

    # 4) RSI güç kaybı (45 altı) — yalnız zararda (flat pullback'te normal)
    if _losing and rsi < 45:
        pts += 1; sig.append(f"RSI {rsi:.0f} (zayıf)")

    # 5) Dağıtım — son 3 gün düşüş hacmi > yükseliş hacmi (ve zararda)
    try:
        last = df.iloc[-3:]
        chg  = last["Close"].diff()
        up_v = float(last[chg > 0]["Volume"].sum())
        dn_v = float(last[chg < 0]["Volume"].sum())
        if dn_v > up_v * 1.3 and price < entry:
            pts += 1; sig.append("Dağıtım hacmi")
    except Exception:
        pass

    # 6) Göreceli zayıflık — son 3 gün endeksten belirgin kötü (yalnız ZARARDA;
    #    taze pozisyonda anında DİKKAT vermesin)
    if _losing and xu100 is not None and len(xu100) > 3 and len(close) > 3:
        try:
            stk = (float(close.iloc[-1]) / float(close.iloc[-4]) - 1) * 100
            idx = (float(xu100["Close"].iloc[-1]) / float(xu100["Close"].iloc[-4]) - 1) * 100
            if stk < idx - 1.5 and stk < 0:
                pts += 1; sig.append("Endeksten zayıf")
        except Exception:
            pass

    # 7) Stop tehlike bölgesi — fiyat stopun hemen üstünde (%1.5)
    if stop and stop < price <= stop * 1.015:
        pts += 2; sig.append("Stop bölgesine yakın")

    # 8) Zarar eşiği — vur-kaç: küçük zararı büyütme
    if   loss_pct <= -2.5: pts += 2; sig.append(f"Zarar %{loss_pct:.1f}")
    elif loss_pct <= -1.5: pts += 1; sig.append(f"Zarar %{loss_pct:.1f}")

    # 9) GÜN İÇİ İVME (DDE 5dk barlarından, monitor sağlar) — günlük barların
    # göremediği saat-içi kırılmayı yakalar (ALKIM vakası: tepede takviye).
    if intraday_chg is not None:
        if   intraday_chg <= -1.2: pts += 2; sig.append(f"Gün içi sert düşüş ({intraday_chg:+.1f}%/30dk)")
        elif intraday_chg <= -0.6: pts += 1; sig.append(f"Gün içi ivme aşağı ({intraday_chg:+.1f}%/30dk)")

    # ── DİP/DESTEK KORUMASI ───────────────────────────────────────────────────
    # Fiyat yakın swing-dibinde (destek) ve dibi HENÜZ kesin kırmadıysa,
    # buradaki "zayıflık" sinyalleri (MA altı, 5-gün dibi, gün içi düşüş) çoğu
    # zaman bounce ÖNCESİ gürültüdür → ERKEN_ÇIK'a YÜKSELTME (dibi sattırma!).
    # Sadece destek − 1 ATR altına KESİN inerse erken çıkışa izin ver.
    # (Kullanıcı vakası: MGROS dip desteğindeyken erken çık verdi, çıkmadı,
    #  sonra DEVAM'a döndü — haklıydı. Grid'deki destek-bölgesi mantığıyla aynı.)
    try:
        if pts >= 5 and len(close) >= 6:
            _swing = float(close.iloc[-10:].min()) if len(close) >= 10 else float(close.iloc[-6:].min())
            _atr   = price * (float(score.get("atr_pct", 2.0) or 2.0) / 100.0)
            _at_support    = _swing <= price <= _swing + 1.0 * _atr
            _broke_support = price < _swing - 1.0 * _atr
            if _at_support and not _broke_support:
                sig.append("⚓ Dip desteğinde — sat-ma, kesin kırılırsa çık")
                pts = 4   # ERKEN_ÇIK'a yükseltme; en fazla ZAYIFLAMA (izle)
    except Exception:
        pass

    msg = " | ".join(sig)
    if pts >= 5:
        return "ERKEN_ÇIK", msg, pts
    if pts >= 3:
        return "ZAYIFLAMA", msg, pts
    return "DEVAM", "", pts


# ─── Ana Analiz ──────────────────────────────────────────────────────────────

JOURNAL_PATH = BASE / "picks_journal.json"


def _journal_record(top_picks, regime: str = ""):
    """ÖNERİ KARNESİ: günün önerilerini kaydet (alınsın ya da alınmasın).
    (tarih, sembol) başına TEK kayıt — günün İLK önerisi saklanır, sonraki
    tazelemeler ezmez. Amaç: 30-50 kayıt sonra hangi skor/koşulların gerçekten
    tuttuğunu VERİYLE görmek (parametre ayarı hisle değil kanıtla yapılır)."""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            j = json.loads(JOURNAL_PATH.read_text(encoding="utf-8"))
        except Exception:
            j = []
        seen = {(r.get("date"), r.get("symbol")) for r in j}
        added = 0
        for p in top_picks or []:
            if (today, p.get("symbol")) in seen:
                continue
            j.append({
                "date": today, "symbol": p["symbol"], "rank": p.get("rank", 0),
                "price": p.get("price", 0),
                "entry_score": p.get("entry_score", 0),
                "total_score": p.get("total_score", 0),
                "rr_ratio":  p.get("rr_ratio", 0),
                "atr_pct":   p.get("atr_pct", 0),
                "stop_loss": p.get("stop_loss", 0),
                "target1":   p.get("target1", 0),
                "timeframe": p.get("timeframe", ""),
                "mode":      STRATEGY_MODE,
                "regime":    regime,
            })
            added += 1
        if added:
            JOURNAL_PATH.write_text(json.dumps(j, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    except Exception as e:
        print(f"[Advisor] Karne kayıt hatası: {e}")


def _journal_evaluate(data: dict):
    """Karnedeki eski kayıtların SONUÇLARINI doldur: öneri sonrası 1g/3g getiri +
    3 gün içinde hedef/stop temas etti mi. Veri zaten indirilmiş günlük barlardan —
    ek indirme YOK. Özet Firebase'e yazılır (kart/inceleme için)."""
    try:
        j = json.loads(JOURNAL_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    changed = False
    for r in j:
        if r.get("done") or not r.get("price"):
            continue
        df = data.get(r.get("symbol"))
        if df is None or len(df) < 2:
            continue
        try:
            idx = [d.strftime("%Y-%m-%d") for d in df.index]
            pos = [i for i, d in enumerate(idx) if d <= r["date"]]
            if not pos:
                continue
            i0 = pos[-1]                      # öneri günü (veya öncesindeki son bar)
            after = df.iloc[i0 + 1:]
            if len(after) >= 1:
                r["ret_1d"] = round((float(after["Close"].iloc[0]) / r["price"] - 1) * 100, 2)
                changed = True
            if len(after) >= 3:
                r["ret_3d"] = round((float(after["Close"].iloc[2]) / r["price"] - 1) * 100, 2)
                w = after.iloc[:3]
                r["hit_target"] = bool(r.get("target1") and float(w["High"].max()) >= r["target1"])
                r["hit_stop"]   = bool(r.get("stop_loss") and float(w["Low"].min()) <= r["stop_loss"])
                r["done"] = True
                changed = True
        except Exception:
            continue
    if changed:
        try:
            JOURNAL_PATH.write_text(json.dumps(j, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
        except Exception:
            pass
    # Özet → Firebase (advisor/journal)
    try:
        import requests as _rq
        done = [r for r in j if r.get("done")]
        if done:
            n = len(done)
            _rq.patch(f"{FIREBASE_URL}/gridtracker/advisor/journal.json", json={
                "n": n,
                "hit_target_pct": round(100 * sum(1 for r in done if r.get("hit_target")) / n),
                "hit_stop_pct":   round(100 * sum(1 for r in done if r.get("hit_stop")) / n),
                "avg_ret_1d": round(sum(r.get("ret_1d", 0) for r in done) / n, 2),
                "avg_ret_3d": round(sum(r.get("ret_3d", 0) for r in done) / n, 2),
                "ts": time.time(),
            }, timeout=8)
    except Exception:
        pass


def _market_regime(xu100) -> tuple[str, str]:
    """
    PİYASA REJİMİ: XU100'ün genel sağlığı. Düşen piyasada en iyi hisse de düşer —
    isabet kaybının ana sebebi. Döner: (seviye, açıklama)
      RISK_ON  → normal işlem
      CAUTION  → işlem serbest ama YARIM LOT (lot_info %50 kesilir)
      RISK_OFF → yeni pozisyon önerilmez (bekleme günü)
    """
    try:
        c     = xu100["Close"]
        price = float(c.iloc[-1])
        ma20  = float(c.rolling(20).mean().iloc[-1])
        ma50  = float(c.rolling(50).mean().iloc[-1]) if len(c) >= 50 else ma20
        r3    = (price / float(c.iloc[-4]) - 1) * 100 if len(c) > 3 else 0.0
        below20 = price < ma20
        if below20 and (ma20 < ma50 or r3 <= -2.0):
            return "RISK_OFF", f"XU100 MA20 altı + trend aşağı (3g {r3:+.1f}%)"
        if below20 or r3 <= -1.5:
            return "CAUTION", f"XU100 zayıf (3g {r3:+.1f}%, MA20 {'altı' if below20 else 'üstü'})"
        return "RISK_ON", f"XU100 sağlıklı (3g {r3:+.1f}%)"
    except Exception:
        return "RISK_ON", "XU100 verisi yok (filtre pasif)"


def run_analysis(dry_run: bool = False, quiet: bool = False,
                 refresh_only: bool = False) -> dict:
    # refresh_only=True → sadece top_picks/lot/score_table'ı yeniden üretip
    # Firebase'e yazar; aktif pozisyon mutasyonu, çıkış/öneri push'u ve
    # _sync_position (akşam Excel mutabakatı) ATLANIR. Gün içi öneri tazeleme için.
    symbols = CFG["bist100"]
    sectors = CFG["sectors"]
    state   = _load_state()
    capital = state.get("capital", CFG.get("capital", 0))
    active  = state.get("active")

    if not quiet:
        print(f"[Advisor] {len(symbols)} hisse analiz ediliyor...")

    data = download_all(symbols)

    # ── VERİ TEMİZLİĞİ: Close'u NaN olan barları at ───────────────────────
    # Düşük likidite/veri boşluğu son barı NaN bırakabiliyor → NaN fiyat
    # skorlamayı zehirler (sahte yüksek skor) ve Firebase JSON'ını kırar.
    for _s in list(data.keys()):
        _df = data[_s]
        if _df is not None and "Close" in _df:
            _cln = _df.dropna(subset=["Close"])
            data[_s] = _cln if len(_cln) >= 2 else None

    xu100 = data.get("XU100")

    # ── PİYASA REJİMİ (endeks filtresi) ──────────────────────────────────
    regime, regime_msg = _market_regime(xu100) if xu100 is not None else ("RISK_ON", "veri yok")

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

    # Günlük öneri sıralaması = ENTRY skoru birincil (ŞİMDİ GİRİLEBİLİRLİK),
    # total ikincil. entry_score, üst banda yapışmış (extended) hisseleri
    # cezalandırır → "alır almaz DİKKAT/tepe" durumunu önler. Pür total-sort
    # güçlü ama extended hisseyi (bb_pos>1) seçip hemen uyarı veriyordu.
    # Eşit entry'de daha yüksek total tercih edilir.
    scores.sort(key=lambda x: (x.get("entry_score", 0), x["total_score"]), reverse=True)
    # Giriş skoru < 3.5 olanları öneriden ELE (tepe yapmış, hacimsiz,
    # üst bant üstü gibi kötü giriş noktaları — ne kadar yüksek total
    # skoru olursa olsun "şimdi girilmez")
    # Halihazırda elimizde olan (aktif) hisse öneri listesinde gösterilmez —
    # zaten alınmış, "şimdi gir" önerisi anlamsız.
    _held = (active or {}).get("symbol")
    # ZARAR MOLASI: yakın geçmişte (≈5 işlem günü / 7 takvim günü) zararla
    # kapatılan sembol yeniden ÖNERİLMEZ — "aynı hisseden ikinci kazık" ve
    # intikam-alımı döngüsünü keser (örn. BIMAS iki kez üst üste).
    _cooldown = set()
    _today_d  = datetime.now().date()
    for _h in state.get("history", []):
        try:
            if isinstance(_h, dict) and _h.get("pnl_tl", 0) < 0:
                _xd = datetime.strptime(_h.get("exit_date", ""), "%Y-%m-%d").date()
                if (_today_d - _xd).days <= 7:
                    _cooldown.add(_h.get("symbol"))
        except Exception:
            pass
    eligible = [s for s in scores
                if s["timeframe"] != "ÖNERİLMEZ"
                and s.get("entry_score", 0) >= 3.0   # extended/aşırı cezalı hisseleri
                # ele (3.5 fazla katı, 2.5 fazla gevşekti); 3.0 dengeli giriş tabanı
                and s.get("bb_pos", 0.5) < 0.65      # ÜST BANTTAN ALDIRMA + backtest
                # optimumu: bb<0.65 → 2y backtest'te PF 2.31 (0.70'te 2.00, 0.55'te
                # 1.42). Bandın alt-orta kısmı, yukarı bol yer, tepe değil.
                and s.get("rsi", 50) < 65            # RSI<65: backtest PF 2.10 (70'te
                # 2.00). Aşırı alımı (check_exit RSI≥72 DİKKAT) baştan eler.
                and s["symbol"] != _held
                and s["symbol"] not in _cooldown]
    if _cooldown and not quiet:
        print(f"[Advisor] Zarar molası (7g): {', '.join(sorted(_cooldown))} önerilmeyecek")
    top_picks = [{**s, "rank": i+1} for i, s in enumerate(eligible[:3])]

    # ── HİSTEREZİS (gün-içi tazelemede #1 seksek oynamasın) ────────────────
    # Skorlar başa baş iken küçük fiyat oynamaları #1'i dakikalar içinde
    # değiştirebiliyor (BRISA→ALKIM gibi) → kullanıcı karar veremiyor.
    # Kural: yeni aday, önceki #1'in GÜNCEL giriş skorunu en az 0.8 puan
    # farkla geçmedikçe önceki #1 korunur. (Önceki #1 elenmiş/uygunsuzsa
    # doğal olarak değişir.)
    if refresh_only and top_picks:
        try:
            _old   = json.loads(RESULT_PATH.read_text(encoding="utf-8")) if RESULT_PATH.exists() else {}
            _prev1 = ((_old.get("top_picks") or [{}])[0] or {}).get("symbol")
            _new1  = top_picks[0]["symbol"]
            if _prev1 and _new1 != _prev1:
                _prev_pick = next((s for s in eligible if s["symbol"] == _prev1), None)
                if _prev_pick:
                    _gap = (top_picks[0].get("entry_score", 0)
                            - _prev_pick.get("entry_score", 0))
                    if _gap < 0.8:
                        _ordered = [_prev_pick] + [p for p in eligible if p["symbol"] != _prev1]
                        top_picks = [{**s, "rank": i+1} for i, s in enumerate(_ordered[:3])]
        except Exception:
            pass

    # ── "BUGÜN İŞLEM YOK" KARARI ────────────────────────────────────────────
    # Tüm BIST50'de entry_score ≥ 6.5 olan hisse sayısı ≤ 1 ise kaliteli
    # kurulum yok → aktif pozisyon yoksa nakit kal, güce bekle.
    high_quality = [s for s in eligible if s.get("entry_score", 0) >= 6.5]
    # GÜNLÜK-AKTİF HEDEF: kullanıcı her gün en iyi skorlu hissede al-sat yapmak
    # istiyor; günleri boş geçmemek esas. Bu yüzden "entry≥6.5 olan ≥2 hisse"
    # gibi katı kalite kapısı KALDIRILDI. Artık yalnızca şu iki durumda dur:
    #   • Piyasa RISK_OFF (düşüşte — en iyi hisse de düşer), VEYA
    #   • Eligible içindeki EN İYİ aday bile zayıf (entry_score < 5.0).
    # Aksi halde en iyi skorlu aday önerilir (eligible zaten R/K≥1.2 + entry≥3.5
    # + zarar molası + haftalık trend filtrelerinden geçmiş "şimdi girilebilir"ler).
    # Eligible zaten total≥5.0 (timeframe ÖNERİLMEZ değil) + R/K≥1.0 + entry≥3.0
    # + bant-içi (bb<1.0) filtrelerinden geçmiş "şimdi girilebilir" hisseler.
    # Bu yüzden ek total kapısına gerek yok: eligible varsa en iyi-girişli aday
    # önerilir. Yalnız RISK_OFF'ta veya hiç eligible yoksa dur.
    no_trade_today = (not active) and (regime == "RISK_OFF" or not eligible)

    # Aktif pozisyon çıkış kontrolü
    exit_signal = {"symbol": None, "signal": "—", "score_now": 0.0, "score_prev": 0.0, "message": ""}
    new_pick_for_exit = None

    if active:
        sym = active["symbol"]
        active_score_data = next((s for s in scores if s["symbol"] == sym), None)
        if active_score_data:
            signal, msg, exit_pts = check_exit(active, active_score_data)
            exit_signal = {
                "symbol":     sym,
                "signal":     signal,
                "exit_pts":   exit_pts,
                "score_now":  active_score_data["total_score"],
                "score_prev": active.get("last_score", active_score_data["total_score"]),
                "message":    msg,
            }
            # Alternatif sırala
            alts = [s for s in eligible if s["symbol"] != sym]
            if alts:
                if signal in ("ÇIK", "ACİL_ÇIK"):
                    # ÇIK → giriş kalitesine göre sırala
                    alts_sorted = sorted(alts, key=lambda x: x.get("entry_score", 0), reverse=True)
                else:
                    alts_sorted = sorted(alts, key=lambda x: x.get("entry_score", 0), reverse=True)
                new_pick_for_exit = alts_sorted[0]

                # DEĞİŞTİR kontrolü: aktif hisse DEVAM'dayken çok daha iyi alternatif var mı?
                if signal == "DEVAM" and active_score_data:
                    best_alt   = alts_sorted[0]
                    active_es  = active_score_data.get("entry_score", active_score_data["total_score"])
                    best_es    = best_alt.get("entry_score", best_alt["total_score"])
                    if best_es - active_es >= 2.5 and best_alt.get("rr_ratio", 0) >= 2.0:
                        signal = "DEĞİŞTİR"
                        msg    = (f"{best_alt['symbol']} daha iyi fırsat "
                                  f"(Giriş: {best_es:.1f}/10 vs aktif: {active_es:.1f}/10)")
                        exit_signal["signal"]  = signal
                        exit_signal["message"] = msg

    # Lot hesapları (önerilen hisseler için)
    lot_info = {}
    if capital > 0:
        # Kullanılabilir sermaye = TOPLAM sermaye ± gerçekleşmemiş K/Z.
        # (Kullanıcı tek pozisyonla rotasyon yapıyor: sıradaki hisseyi almak için
        # mevcudu satar → eline ~tam sermaye geçer. ESKİ HATA: avail = sadece
        # pozisyonun değeri [qty×fiyat] alınıyordu → boştaki nakit sayılmıyor,
        # pozisyon tutarken öneri AZ lot çıkıyor, satıp flat olunca lot ZIPLIYOR.)
        avail_capital = capital
        if active:
            qty   = active.get("qty", 0)
            entry = active.get("entry_price", 0) or 0
            act_score = next((s for s in scores if s["symbol"] == active["symbol"]), None)
            if act_score and qty > 0 and entry > 0:
                _unreal = qty * (act_score["price"] - entry)   # +kâr / −zarar
                avail_capital = capital + _unreal
                # NaN/geçersiz/negatifse tam sermayeye düş
                if (not avail_capital or avail_capital != avail_capital
                        or avail_capital <= 0):
                    avail_capital = capital

        # REJİM çarpanı (RISK_OFF zaten no_trade; CAUTION=zayıf piyasa)
        _regime_factor = 0.5 if regime == "CAUTION" else 1.0

        for p in top_picks:
            # ── DOZLAMA: min(rejim, konviksiyon) — ÇİFT CEZA YOK ──────────────
            # Eskiden rejim × konviksiyon ÇARPILIYORDU (0.5×0.55=0.275) → çok
            # nakit boşta kalıyordu. Artık BAĞLAYICI KISIT (min) kullanılır:
            # zayıf piyasada VEYA zayıf kurulumda hangisi daha kısıtlıysa o.
            # Kurulum kalitesi (R/K + giriş skoru) → konviksiyon dozu.
            _rr = p.get("rr_ratio", 1.0) or 1.0
            _es = p.get("entry_score", 0) or 0
            if   _rr >= 1.8 and _es >= 5.5: _conv, _clabel = 1.00, "Güçlü"
            elif _rr >= 1.4 and _es >= 4.5: _conv, _clabel = 0.85, "İyi"
            elif _rr >= 1.2 and _es >= 4.0: _conv, _clabel = 0.70, "Orta"
            else:                           _conv, _clabel = 0.55, "Temkinli"
            _factor = min(_regime_factor, _conv)
            _cap = avail_capital * _factor
            lots = calc_lots(_cap, p["price"])
            # ── KADEMELİ POZİSYON: %75 ana giriş + %25 fırsat (pull-back) ──
            # 1) Ana giriş (%75): giriş bölgesinde hemen
            # 2) Fırsat alımı (%25): geri çekilmede — ortalama maliyet iyileşir
            lots_main  = calc_lots(_cap * 0.75, p["price"])
            lots_dip   = calc_lots(_cap * 0.25, p["price"])
            dip_target = round(p["price"] * 0.97, 4)   # %3 geri çekilme hedefi
            lot_info[p["symbol"]] = {
                "lots":       lots,            # konviksiyon dozlu toplam
                "lots_main":  lots_main,       # %75 ana giriş
                "lots_dip":   lots_dip,        # %25 fırsat alımı
                "dip_price":  dip_target,      # fırsat alım fiyatı (~%3 düşük)
                "price":      p["price"],
                "conviction": _clabel,         # Güçlü/İyi/Orta/Temkinli
                "conv_factor": _conv,          # 0.55-1.0 doz çarpanı
                "cost":       round(lots_main * p["price"] * (1 + CFG["commission_rate"]), 2),
                "cost_total": round(lots * p["price"] * (1 + CFG["commission_rate"]), 2),
            }

    # Tracker P&L
    try:
        from tracker import track
        tracker_data = track(state)
    except Exception as e:
        tracker_data = {"error": str(e)}

    # Aktif (elimizdeki) hissenin tam skor verisi — top_picks'ten elendiği
    # için kart bunu ayrı alandan okur (bar/stop/hedef gösterimi).
    active_pick_data = None
    if active:
        _ap = next((s for s in scores if s["symbol"] == active["symbol"]), None)
        if _ap:
            active_pick_data = {**_ap, "rank": 0}
            # KİLİTLİ seviyeler: _ap'in target/stop'u her döngüde GÜNCEL FİYATLA
            # yeniden hesaplanır → hedef fiyatı kovalayıp yukarı kaçar. Pozisyon
            # açıkken state.active'deki kilitli (girişte sabit + trailing) değerleri
            # kullan ki hedef sabit ve ulaşılabilir kalsın.
            for _k in ("target1", "target2", "stop_loss", "hard_stop"):
                if active.get(_k):
                    active_pick_data[_k] = active[_k]

    ts = time.time()
    result = {
        "ts":             ts,
        "ts_str":         _ts_str(ts),
        "capital":        capital,
        "top_picks":      top_picks,
        "active_pick":    active_pick_data,
        "exit_signal":    exit_signal,
        "lot_info":       lot_info,
        "no_trade_today": no_trade_today,
        "high_quality_count": len(high_quality),
        "market_regime":  {"level": regime, "msg": regime_msg},
        "tracker":     tracker_data,
        "score_table": {s["symbol"]: {"total": s["total_score"], "rank": i+1,
                                       "timeframe": s["timeframe"],
                                       "entry": s.get("entry_score", 0),
                                       "rr": s.get("rr_ratio", 0),
                                       "bb": s.get("bb_pos", 0)}
                        for i, s in enumerate(scores)},
    }

    if not dry_run:
        RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if not quiet:
            print(f"[Advisor] Sonuç yazıldı: {RESULT_PATH}")

        # Firebase'e yaz (telefon erişimi için)
        _firebase_push(result)

        # Öneri karnesi: günün önerilerini kaydet (her çalıştırmada; gün içinde
        # ilk kayıt korunur, mükerrer yazılmaz)
        _journal_record(top_picks, regime)

        # refresh_only: sadece öneriler tazelendi → state mutasyonu / push /
        # _sync_position'a dokunma, çık.
        if refresh_only:
            return result

        # Karne değerlendirme: eski kayıtların sonuçlarını doldur (akşam koşusunda;
        # zaten indirilmiş günlük veriyle, ek maliyet yok)
        _journal_evaluate(data)

        # State güncelle
        if active:
            state["active"]["last_score"] = exit_signal["score_now"]
            # Hedef fiyatlar yoksa aktif hisse için otomatik doldur
            if not state["active"].get("target1"):
                active_pick = next((s for s in scores if s["symbol"] == active["symbol"]), None)
                if active_pick:
                    state["active"]["target1"]  = active_pick["target1"]
                    state["active"]["target2"]  = active_pick["target2"]
                    state["active"]["stop_loss"] = state["active"].get("stop_loss") or active_pick["stop_loss"]
                    state["active"]["hard_stop"] = state["active"].get("hard_stop") or active_pick.get("hard_stop")
            # ÇIK sinyalinde: önerilen yeni hisseyi pending_buy'a kaydet.
            # Kullanıcı bu hisseyi alırsa monitor otomatik aktif pozisyon yapar.
            if exit_signal["signal"] in ("ÇIK", "ACİL_ÇIK") and new_pick_for_exit:
                np = new_pick_for_exit
                state["pending_buy"] = {
                    "symbol":     np["symbol"],
                    "stop_loss":  np.get("stop_loss", 0),
                    "hard_stop":  np.get("hard_stop", 0),
                    "target1":    np.get("target1", 0),
                    "target2":    np.get("target2", 0),
                    "score":      np.get("total_score", 0),
                    "timeframe":  np.get("timeframe", ""),
                    "entry_low":  np.get("entry_zone", {}).get("low", 0),
                    "entry_high": np.get("entry_zone", {}).get("high", 0),
                }
                _record_recommendation(state, np["symbol"], np)
        # Aktif yokken günlük öneri verildiyse onu da kaydet
        if top_picks and not active:
            _record_recommendation(state, top_picks[0]["symbol"], top_picks[0])
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
            elif no_trade_today:
                # Kaliteli kurulum yok VEYA piyasa rejimi negatif → nakit kal
                _why = (f"📉 Piyasa rejimi: {regime_msg}\n"
                        if regime == "RISK_OFF" else
                        "Bant-içi (R/K≥1.0, temiz giriş) uygun aday yok — zayıf gün.\n")
                notifier._send(
                    "⏸ Bugün Bekleme Günü",
                    _why +
                    f"Bugün nakit kalmak en doğrusu — düşen piyasada en iyi hisse de düşer.\n"
                    f"Koşullar düzelince yeni öneri gelecek.",
                    priority="default", tags="hourglass_not_done")
            elif top_picks and not active:
                # Aktif pozisyon yoksa günlük öneriyi bildir
                notifier.send_daily_pick(top_picks[0], lot_info.get(top_picks[0]["symbol"]))
        except Exception as e:
            print(f"[Advisor] Push hatası: {e}")

        # ── OTOMATİK POZİSYON TAKİBİ ──────────────────────────────────────
        # 1.xlsx bu noktada (akşam, grid_tracker_service sonrası) güncel.
        # Satış/alış algılayıp pozisyonu otomatik günceller.
        _sync_position()

    return result


def _sync_position():
    """
    OTOMATİK POZİSYON TAKİBİ — 1.xlsx'ten GÜN İÇİ TÜM İŞLEMLERİ uzlaştırır.
    1.xlsx akşam 18:35'te oluştuğu için advisor --run içinde (18:40) çağrılır.

    Mantık (çok-sembollü):
      • Reconcile edilecek semboller = aktif + pending_buy + gün içi ÖNERİLEN
        (recommended_today). Yani TTKOM→AKSA gibi geçişlerde her iki hisse de.
      • Her sembol için 1.xlsx'teki alış/satışlara bakılır:
          - Satış yapılmışsa → gerçekleşen K/Z history'ye yazılır
            (monitor'ün gün içi koyduğu 'provisional' tahmini kayıt değiştirilir).
          - Hâlâ elde tutuluyorsa (net>0) → aktif pozisyon o olur.
      • Hiçbiri elde değilse → active = None (kart "öneri bekle" moduna geçer).
    """
    try:
        import notifier
        from tracker import _read_excel
        state = _load_state()
        today = datetime.now().strftime("%Y-%m-%d")

        # Reconcile edilecek sembol listesi + her birinin öneri bilgisi (stop/hedef)
        rec_map, syms = {}, []
        def _add(sym, info=None):
            if sym and sym not in syms:
                syms.append(sym)
            if sym and info and sym not in rec_map:
                rec_map[sym] = info
        if state.get("active"):       _add(state["active"]["symbol"], state["active"])
        if state.get("pending_buy"):  _add(state["pending_buy"]["symbol"], state["pending_buy"])
        for r in state.get("recommended_today", []):
            if isinstance(r, dict):   _add(r.get("symbol"), r)

        history = state.setdefault("history", [])

        def _already_final(sym):
            return any(h.get("symbol") == sym and h.get("exit_date") == today
                       and not h.get("provisional") for h in history)

        held, closed = {}, []
        _prev_active     = state.get("active")
        _prev_active_sym = (_prev_active or {}).get("symbol")
        _active_in_excel = False   # aktif sembolün 1.xlsx'te HERHANGİ bir kaydı var mı?
        for sym in syms:
            buys, sells = _read_excel(sym)
            if not buys and not sells:
                continue
            if sym == _prev_active_sym:
                _active_in_excel = True
            buy_qty  = sum(b["execQty"] for b in buys)
            sell_qty = sum(s["execQty"] for s in sells)
            # Maliyet: bugün alım varsa ondan, yoksa (devreden pozisyon) state'ten/öneriden
            if buy_qty > 0:
                avg_cost = sum(b["execAmount"] + b["commission"] for b in buys) / buy_qty
                # ÇOK-GÜNLÜ TAKVİYE (fırsat alımı): pozisyon ÖNCEKİ günden devrediyorsa,
                # 1.xlsx yalnızca bugünün alışlarını içerir. Bugünkü lotlar devreden
                # lotların ÜSTÜNE eklenir (toplam lot + ağırlıklı ort. maliyet) — aksi
                # halde pozisyon "sadece bugünkü lotlar" olarak EZİLİYORDU.
                if (_prev_active_sym == sym
                        and (_prev_active or {}).get("entry_date", today) < today
                        and (_prev_active or {}).get("qty", 0) > 0
                        and (_prev_active or {}).get("entry_price", 0) > 0):
                    _po_qty = _prev_active["qty"]
                    _po_avg = _prev_active["entry_price"]
                    _tot    = _po_qty + buy_qty
                    avg_cost = (_po_avg * _po_qty + avg_cost * buy_qty) / _tot
                    buy_qty  = _tot
                    print(f"[Advisor] {sym}: devreden {_po_qty} + bugün alınan lotlar birleştirildi "
                          f"→ {_tot} lot @ {avg_cost:.4f}")
            elif state.get("active") and state["active"]["symbol"] == sym:
                avg_cost = state["active"].get("entry_price", 0.0)
                buy_qty  = state["active"].get("qty", buy_qty)
            elif (rec_map.get(sym) or {}).get("entry_price"):
                avg_cost = rec_map[sym]["entry_price"]
                buy_qty  = rec_map[sym].get("qty", buy_qty)
            else:
                avg_cost = 0.0
            net = buy_qty - sell_qty

            # Gerçekleşen satış → history (provisional tahmini kaydı temizleyip yenisini yaz)
            if sell_qty > 0 and avg_cost > 0 and not _already_final(sym):
                sell_amount = sum(s["execAmount"] - s["commission"] for s in sells)
                pnl_tl  = sell_amount - (avg_cost * sell_qty)
                pnl_pct = (pnl_tl / (avg_cost * sell_qty) * 100) if avg_cost and sell_qty else 0
                exit_px = sell_amount / sell_qty if sell_qty else 0
                history[:] = [h for h in history
                              if not (h.get("symbol") == sym and h.get("provisional"))]
                history.append({
                    "symbol": sym,
                    "entry_date": (rec_map.get(sym) or {}).get("entry_date", today),
                    "exit_date":  today,
                    "entry_price": round(avg_cost, 4),
                    "exit_price":  round(exit_px, 4),
                    "qty":  sell_qty,
                    "pnl_tl":  round(pnl_tl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "exit_reason": "Otomatik (Excel)",
                })
                closed.append((sym, avg_cost, exit_px, pnl_tl, pnl_pct))

            if net > 0:
                held[sym] = (net, avg_cost, rec_map.get(sym) or {})

        # Aktif pozisyon = hâlâ elde tutulan (en büyük TL değerli); yoksa None
        if held:
            asym = max(held, key=lambda s: held[s][0] * held[s][1])
            net, avg, rec = held[asym]
            state["active"] = {
                "symbol": asym,
                "entry_date": rec.get("entry_date", today),
                "entry_price": round(avg, 4),
                "qty": net,
                "stop_loss": rec.get("stop_loss", 0),
                "hard_stop": rec.get("hard_stop", 0),
                "target1":   rec.get("target1", 0),
                "target2":   rec.get("target2", 0),
                "last_score": rec.get("score", 0),
                "timeframe":  rec.get("timeframe", ""),
            }
            # KRİTİK: Trailing stop bookkeeping'ini KORU. Aksi halde ertesi gün
            # entry_stop eksik kalır → trail_dist negatif → stop fiyatın üstüne
            # çıkar → sahte stop-out tetiklenir.
            for _tf in ("peak_price", "entry_stop", "entry_hard"):
                if rec.get(_tf) is not None:
                    state["active"][_tf] = rec[_tf]
        elif _prev_active_sym and not _active_in_excel:
            # KRİTİK KORUMA: Aktif pozisyonun 1.xlsx'te HİÇ kaydı yok.
            # 1.xlsx yalnızca O GÜNÜN işlemlerini içerir — pozisyon birden çok gün
            # tutuluyorsa ve o gün işlem yapılmadıysa dosyada görünmez. Bu durumda
            # pozisyon SATILMIŞ DEĞİL, sadece o gün dokunulmamış → AYNEN KORU.
            # (Eski davranış: sessizce siliyordu → kullanıcı elinde hisseyle
            # takipsiz/alarmsız kalıyordu.)
            print(f"[Advisor] {_prev_active_sym}: bugün Excel kaydı yok → pozisyon korunuyor (satış yok).")
        else:
            state["active"] = None

        state["pending_buy"] = None
        # recommended_today: son 7 günü tut (ertesi gün alımlar için), aktif olanı çıkar
        _held_sym = (state.get("active") or {}).get("symbol")
        _cut = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        state["recommended_today"] = [r for r in state.get("recommended_today", [])
                                      if isinstance(r, dict) and r.get("date", "") >= _cut
                                      and r.get("symbol") != _held_sym]
        _save_state(state)

        # Kapanan her pozisyon için bildirim
        for sym, avg, exit_px, pnl_tl, pnl_pct in closed:
            print(f"[Advisor] POZİSYON KAPANDI: {sym} K/Z: {pnl_tl:+.0f} TL")
            try:
                notifier._send(
                    f"✅ {sym} SATILDI",
                    f"Pozisyon kapandı.\n"
                    f"Giriş: {avg:.2f} → Çıkış: {exit_px:.2f} TL\n"
                    f"Kâr/Zarar: {pnl_tl:+,.0f} TL ({pnl_pct:+.1f}%)".replace(",", "."),
                    tags="white_check_mark")
            except: pass
        if state.get("active"):
            print(f"[Advisor] AKTİF POZİSYON: {state['active']['symbol']} "
                  f"{state['active']['qty']} lot")
    except Exception as e:
        print(f"[Advisor] Pozisyon senkron hatası: {e}")


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
        signal, msg, exit_pts = check_exit(active, score)
        print(f"\n[{sym}] Skor: {score['total_score']:.1f}/10 | RSI: {score['rsi']:.0f} | Çıkış Puanı: {exit_pts} | Sinyal: {signal}")
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
