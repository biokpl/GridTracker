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

    # ── Stop & Hedef ──────────────────────────────────────────────────────
    # Stop yerleşimi: YAKIN swing dibi + küçük ATR tamponu (fitil/stop avı için).
    #   • Son 10 günün dibinin 0.3 ATR ALTINA koy → bariz dip seviyesinde değil
    #   • Girişten 1.0–1.8 ATR bandında sınırla → R/K bozulmasın, kapanış onayı
    #     zaten fitili elediği için stopun aşırı geniş olmasına gerek yok.
    _swing_low   = float(close.iloc[-10:].min()) if len(close) >= 10 else float(close.min())
    _struct_stop = _swing_low - 0.3 * atr_val   # swing dibinin hemen altı
    _near_stop   = price - 1.0 * atr_val         # en yakın (min mesafe)
    _far_stop    = price - 1.8 * atr_val         # en uzak (risk tavanı)
    stop_loss    = round(min(max(_struct_stop, _far_stop), _near_stop), 4)
    # Felaket stopu: kapanış beklemeden ANINDA çıkılacak seviye (stop'un ~0.8 ATR altı)
    hard_stop    = round(stop_loss - 0.8 * atr_val, 4)
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
    if total < 5.0:
        exit_pts += 3
        signals.append(f"Teknik skor {total:.1f}/10")
    elif total < 6.5:
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

    # Günlük öneri = ŞİMDİ GİRİLECEK hisse → giriş kalitesi (entry_score)
    # belirleyici. total_score genel kaliteyi zaten entry_score içeriyor
    # (entry_score = total + giriş bonusu/cezası). Böylece tepe yapmış
    # (yüksek total ama kötü giriş) hisseler öne çıkmaz.
    scores.sort(key=lambda x: x.get("entry_score", x["total_score"]), reverse=True)
    # Giriş skoru < 3.5 olanları öneriden ELE (tepe yapmış, hacimsiz,
    # üst bant üstü gibi kötü giriş noktaları — ne kadar yüksek total
    # skoru olursa olsun "şimdi girilmez")
    # Halihazırda elimizde olan (aktif) hisse öneri listesinde gösterilmez —
    # zaten alınmış, "şimdi gir" önerisi anlamsız.
    _held = (active or {}).get("symbol")
    eligible = [s for s in scores
                if s["timeframe"] != "ÖNERİLMEZ"
                and s.get("entry_score", 0) >= 3.5
                and s["symbol"] != _held]
    top_picks = [{**s, "rank": i+1} for i, s in enumerate(eligible[:3])]

    # ── "BUGÜN İŞLEM YOK" KARARI ────────────────────────────────────────────
    # Tüm BIST50'de entry_score ≥ 6.5 olan hisse sayısı ≤ 1 ise kaliteli
    # kurulum yok → aktif pozisyon yoksa nakit kal, güce bekle.
    high_quality = [s for s in eligible if s.get("entry_score", 0) >= 6.5]
    no_trade_today = (not active) and len(high_quality) <= 1

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
            # ── KADEMELİ POZİSYON: %60 ana giriş + %25 fırsat (pull-back) ──
            # Tek seferde tam sermaye yerine iki kademe:
            # 1) Ana giriş (%60): giriş bölgesinde hemen
            # 2) Fırsat alımı (%25): hisse %2-3 geri çekilirse — ortalama maliyet iyileşir
            # 3) Nakit tampon (%15): her zaman likit kal
            lots_main  = calc_lots(avail_capital * 0.60, p["price"])
            lots_dip   = calc_lots(avail_capital * 0.25, p["price"])
            dip_target = round(p["price"] * 0.97, 4)   # %3 geri çekilme hedefi
            lot_info[p["symbol"]] = {
                "lots":       lots,            # tam sermaye (eski davranış - backward compat)
                "lots_main":  lots_main,       # %60 ana giriş
                "lots_dip":   lots_dip,        # %25 fırsat alımı
                "dip_price":  dip_target,      # fırsat alım fiyatı (~%3 düşük)
                "price":      p["price"],
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
                # Kaliteli kurulum yok → nakit kal, bekleme bildirimi
                notifier._send(
                    "⏸ Bugün Bekleme Günü",
                    f"BİST50'de entry_score ≥6.5 olan hisse {len(high_quality)} adet.\n"
                    f"Kaliteli kurulum yok — bugün nakit kalmak en doğrusu.\n"
                    f"Yarın yeni analiz yapılacak.",
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
        for sym in syms:
            buys, sells = _read_excel(sym)
            if not buys and not sells:
                continue
            buy_qty  = sum(b["execQty"] for b in buys)
            sell_qty = sum(s["execQty"] for s in sells)
            # Maliyet: bugün alım varsa ondan, yoksa (devreden pozisyon) state'ten/öneriden
            if buy_qty > 0:
                avg_cost = sum(b["execAmount"] + b["commission"] for b in buys) / buy_qty
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
