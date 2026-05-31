"""
monitor.pyw — Sürekli çalışan arka plan servisi
Her 15 dakikada bir aktif pozisyonu kontrol eder, çıkış sinyali oluşursa push gönderir.
Piyasa saatleri: 10:00 – 18:15 (BIST)
"""
import json
import time
import logging
import threading
from datetime import datetime, time as dtime
from pathlib import Path

import warnings
warnings.filterwarnings("ignore")

BASE = Path(__file__).parent

# Log ayarı
log_path = BASE / "monitor.log"
logging.basicConfig(
    filename=str(log_path),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
)
log = logging.getLogger("monitor")

# Sabitler
CHECK_INTERVAL_MIN   = 15   # Piyasa saatlerinde kontrol aralığı (dakika)
OFF_HOURS_SLEEP_MIN  = 30   # Piyasa dışı uyku (dakika)
MARKET_OPEN          = dtime(10, 0)
MARKET_CLOSE         = dtime(18, 20)
WEEKDAYS             = range(0, 5)  # Pazartesi–Cuma

# Önceki sinyal (aynı sinyali tekrar tekrar gönderme)
_last_signal = {"symbol": None, "signal": None, "sent_at": 0.0}
_signal_lock = threading.Lock()


def _load_cfg():
    return json.loads((BASE / "config.json").read_text(encoding="utf-8"))


def _load_state():
    return json.loads((BASE / "state.json").read_text(encoding="utf-8"))


def _is_market_open() -> bool:
    now = datetime.now()
    if now.weekday() not in WEEKDAYS:
        return False
    t = now.time()
    return MARKET_OPEN <= t <= MARKET_CLOSE


def _should_send(symbol: str, signal: str) -> bool:
    """Aynı sinyal 60 dakika içinde tekrar gönderilmesin."""
    with _signal_lock:
        if (_last_signal["symbol"] == symbol and
                _last_signal["signal"] == signal and
                time.time() - _last_signal["sent_at"] < 3600):
            return False
        _last_signal.update({"symbol": symbol, "signal": signal, "sent_at": time.time()})
    return True


def _check_once():
    """Tek bir kontrol döngüsü."""
    try:
        import advisor
        import notifier

        state  = _load_state()
        active = state.get("active")
        if not active:
            log.info("Aktif pozisyon yok, kontrol atlandı.")
            return

        sym = active["symbol"]
        log.info(f"{sym} kontrol ediliyor...")

        cfg = _load_cfg()

        # ── Hızlı fiyat kontrolü: Excel (MatriksIQ DDE) → Yahoo fallback ──
        import sys as _sys
        _sys.path.insert(0, str(BASE))
        from price_reader import get_price

        live_price, kaynak = get_price(sym)
        log.info(f"{sym} anlık fiyat: {live_price} TL (kaynak: {kaynak})")

        # Stop/Hedef hızlı kontrolü — tam analiz öncesi
        stop  = active.get("stop_loss", 0)
        h1    = active.get("target1", 0)
        h2    = active.get("target2", 0)
        if live_price:
            if stop and live_price < stop:
                log.warning(f"{sym} STOP KIRILDI! {live_price} < {stop}")
                import notifier
                if _should_send(sym, "ACİL_ÇIK"):
                    notifier.send_exit_signal("ACİL_ÇIK", sym,
                        active.get("last_score", 0), active.get("last_score", 0),
                        f"Stop kırıldı! {live_price:.2f} < {stop:.2f} TL", None, {})
                return
            if h2 and live_price >= h2:
                log.info(f"{sym} 2. HEDEF AŞILDI! {live_price} >= {h2}")
            elif h1 and live_price >= h1:
                log.info(f"{sym} 1. HEDEF AŞILDI! {live_price} >= {h1}")

        import yfinance as yf
        import pandas as pd
        import numpy as np

        # Tam teknik analiz için Yahoo (15 dk gecikmeli ama RSI/Bollinger için yeterli)
        raw = yf.download([f"{sym}.IS", "XU100.IS"],
                          period="90d", auto_adjust=True, progress=False, threads=True)

        def _get_df(s):
            ticker = f"{s}.IS"
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    df = raw.xs(ticker, axis=1, level=1).dropna(how="all")
                else:
                    df = raw.dropna(how="all")
                return df if len(df) >= 20 else None
            except:
                return None

        df    = _get_df(sym)
        xu100 = _get_df("XU100")

        # Anlık fiyatı DataFrame'e yansıt (Yahoo gecikmeli olabilir)
        if df is not None and live_price and kaynak == "excel":
            df.iloc[-1, df.columns.get_loc("Close")] = live_price

        if df is None:
            log.warning(f"{sym} için veri alınamadı.")
            return

        all_returns = {
            "r5":  {sym: advisor._pct(float(df["Close"].iloc[-1]), float(df["Close"].iloc[-6]))  if len(df) > 5  else 0},
            "r20": {sym: advisor._pct(float(df["Close"].iloc[-1]), float(df["Close"].iloc[-21])) if len(df) > 20 else 0},
            "r60": {sym: advisor._pct(float(df["Close"].iloc[-1]), float(df["Close"].iloc[-61])) if len(df) > 60 else 0},
        }

        score  = advisor.score_stock(sym, df, xu100, all_returns, cfg["sectors"])
        signal, msg, exit_pts = advisor.check_exit(active, score)

        log.info(f"{sym}: Skor={score['total_score']:.1f}/10  RSI={score['rsi']:.0f}  Çıkış={exit_pts}p  Sinyal={signal}")

        # State güncelle
        state["active"]["last_score"] = score["total_score"]
        from advisor import STATE_PATH, RESULT_PATH
        import advisor as adv_mod
        adv_mod._save_state(state)

        # Minimal result.json + Firebase güncelle (UI + telefon için)
        exit_data = {
            "symbol":     sym,
            "signal":     signal,
            "score_now":  score["total_score"],
            "score_prev": active.get("last_score", score["total_score"]),
            "message":    msg,
        }
        try:
            old = json.loads(RESULT_PATH.read_text(encoding="utf-8")) if RESULT_PATH.exists() else {}
            old["exit_signal"] = exit_data
            old["ts_str"] = datetime.now().strftime("%d.%m.%Y %H:%M")
            RESULT_PATH.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        except:
            pass
        try:
            import requests as _req
            _req.patch(
                "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app/gridtracker/advisor.json",
                json={"exit_signal": exit_data, "ts_str": datetime.now().strftime("%d.%m.%Y %H:%M")},
                timeout=8)
        except:
            pass

        # Push — sadece aksiyon gerektiren sinyallerde, tekrar gönderme önleme
        if signal in ("DİKKAT", "ÇIK", "ACİL_ÇIK", "DEĞİŞTİR") and _should_send(sym, signal):
            # Çıkış için alternatif öner — hızlı: mevcut result.json top_picks'tan al
            new_pick = None
            lot_info = {}
            try:
                rd = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
                picks = [p for p in rd.get("top_picks", []) if p["symbol"] != sym]
                if picks:
                    new_pick = picks[0]
                    lot_info = rd.get("lot_info", {})
            except:
                pass

            notifier.send_exit_signal(
                signal=signal, symbol=sym,
                score_prev=active.get("last_score", score["total_score"]),
                score_now=score["total_score"],
                message=msg,
                new_pick=new_pick,
                lot_info=lot_info,
            )

    except Exception as e:
        log.error(f"Kontrol hatası: {e}", exc_info=True)


def main():
    log.info("Monitor servisi başlatıldı.")
    print("[Monitor] Arka plan servisi başlatıldı. Log:", log_path)

    while True:
        try:
            if _is_market_open():
                _check_once()
                sleep_min = CHECK_INTERVAL_MIN
            else:
                now = datetime.now()
                log.info(f"Piyasa kapalı ({now.strftime('%H:%M')}). {OFF_HOURS_SLEEP_MIN} dk uyuyor.")
                sleep_min = OFF_HOURS_SLEEP_MIN

        except Exception as e:
            log.error(f"Ana döngü hatası: {e}")
            sleep_min = 5

        time.sleep(sleep_min * 60)


if __name__ == "__main__":
    main()
