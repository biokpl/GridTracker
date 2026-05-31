"""
monitor.pyw — İki katmanlı arka plan servisi

Hızlı döngü  (5 sn)  : Excel'den anlık fiyat → stop/hedef → ANINDA bildirim
Yavaş döngü  (15 dk) : Yahoo teknik analiz → RSI/Bollinger/skor → sinyal

Piyasa saatleri: 10:00 – 18:20 (BIST)
"""
import json, sys, time, logging, threading
from datetime import datetime, time as dtime
from pathlib import Path

import warnings
warnings.filterwarnings("ignore")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent

# Log
log_path = BASE / "monitor.log"
logging.basicConfig(
    filename=str(log_path), level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S", encoding="utf-8",
)
log = logging.getLogger("monitor")

# ── Sabitler ─────────────────────────────────────────────────────────────────
FAST_INTERVAL_SEC   = 5     # Fiyat kontrol aralığı (saniye)
SLOW_INTERVAL_MIN   = 15    # Teknik analiz aralığı (dakika)
OFF_HOURS_SLEEP_MIN = 30    # Piyasa dışı uyku
MARKET_OPEN         = dtime(10, 0)
MARKET_CLOSE        = dtime(18, 20)
WEEKDAYS            = range(0, 5)

# Spam koruması: aynı sinyal 60 dk içinde tekrar gönderilmez
_sent = {}
_sent_lock = threading.Lock()

# ── Yardımcılar ───────────────────────────────────────────────────────────────

def _fp(v) -> str:
    """Fiyatı gereksiz sıfır olmadan biçimler: 2.5 → '2.5', 2.73 → '2.73', 64.0 → '64'."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{f:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"

def _load_state() -> dict:
    return json.loads((BASE / "state.json").read_text(encoding="utf-8"))

def _save_state(state: dict):
    (BASE / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def _load_cfg() -> dict:
    return json.loads((BASE / "config.json").read_text(encoding="utf-8"))

def _is_market_open() -> bool:
    now = datetime.now()
    if now.weekday() not in WEEKDAYS: return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE

def _should_send(sym: str, signal: str) -> bool:
    key = f"{sym}:{signal}"
    with _sent_lock:
        last = _sent.get(key, 0)
        if time.time() - last < 3600:
            return False
        _sent[key] = time.time()
    return True

def _reset_signal(sym: str, signal: str):
    """Sinyal değişince eski kaydı sil ki yeni sinyal gönderilsin."""
    key = f"{sym}:{signal}"
    with _sent_lock:
        _sent.pop(key, None)


# ── HIZLI DÖNGÜ: Anlık fiyat → Stop / Hedef kontrolü ────────────────────────

def _fast_price_check():
    """
    Excel'den anlık fiyat okur, stop/hedef kontrolü yapar.
    Tetiklenirse anında push gönderir.
    """
    try:
        sys.path.insert(0, str(BASE))
        from price_reader import get_price
        import notifier

        state  = _load_state()
        active = state.get("active")
        if not active:
            return

        sym   = active["symbol"]
        stop  = active.get("stop_loss", 0)
        h1    = active.get("target1", 0)
        h2    = active.get("target2", 0)
        entry = active.get("entry_price", 0)

        price, kaynak = get_price(sym)
        if not price:
            return

        # P&L hesabı
        qty     = active.get("qty", 0)
        pnl_pct = ((price - entry) / entry * 100) if entry else 0
        pnl_tl  = (price - entry) * qty if (entry and qty) else 0

        # ── ACİL: Stop kırıldı ────────────────────────────────────────────
        if stop and price <= stop:
            if _should_send(sym, "ACİL_ÇIK"):
                log.warning(f"STOP KIRILDI! {sym} {_fp(price)} <= {_fp(stop)}")
                # Anlık alternatif: son result.json'dan al
                new_pick, lot_info = _get_last_alternative(sym)
                notifier.send_exit_signal(
                    "ACİL_ÇIK", sym,
                    active.get("last_score", 0),
                    active.get("last_score", 0),
                    f"Stop kırıldı! {_fp(price)} ₺ ≤ {_fp(stop)} ₺  ({pnl_pct:+.1f}%)",
                    new_pick, lot_info
                )
            return

        # ── 2. Hedef aşıldı ───────────────────────────────────────────────
        if h2 and price >= h2:
            if _should_send(sym, "H2"):
                gain_tl = (h2 - entry) * qty if (entry and qty) else 0
                log.info(f"2. HEDEF AŞILDI! {sym} {_fp(price)} >= {_fp(h2)}")
                new_pick, lot_info = _get_last_alternative(sym)
                notifier.send_exit_signal(
                    "ÇIK", sym,
                    active.get("last_score", 0),
                    active.get("last_score", 0),
                    f"2. Hedef aşıldı! {_fp(price)} ₺  ({pnl_pct:+.1f}%,  +{gain_tl:,.0f} ₺)",
                    new_pick, lot_info
                )
            return

        # ── 1. Hedef aşıldı ───────────────────────────────────────────────
        if h1 and price >= h1:
            if _should_send(sym, "H1"):
                gain_tl = (h1 - entry) * qty if (entry and qty) else 0
                log.info(f"1. HEDEF AŞILDI! {sym} {_fp(price)} >= {_fp(h1)}")
                new_pick, lot_info = _get_last_alternative(sym)
                notifier.send_exit_signal(
                    "ÇIK", sym,
                    active.get("last_score", 0),
                    active.get("last_score", 0),
                    f"1. Hedef aşıldı! {_fp(price)} ₺  ({pnl_pct:+.1f}%,  +{gain_tl:,.0f} ₺)",
                    new_pick, lot_info
                )
            return

        # ── Her şey normal: sadece log ─────────────────────────────────────
        log.debug(f"{sym} {_fp(price)} ₺  {pnl_pct:+.2f}%  (stop:{_fp(stop)}  h1:{_fp(h1)}  h2:{_fp(h2)})  [{kaynak}]")

    except Exception as e:
        log.error(f"Hızlı kontrol hatası: {e}")


def _get_last_alternative(exclude_sym: str):
    """Son result.json'daki en iyi alternatif ve lot bilgisini döner."""
    try:
        from advisor import RESULT_PATH
        d = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        picks = [p for p in d.get("top_picks", []) if p["symbol"] != exclude_sym]
        lot_info = d.get("lot_info", {})
        return (picks[0] if picks else None), lot_info
    except:
        return None, {}


# ── YAVAŞ DÖNGÜ: Tam teknik analiz ───────────────────────────────────────────

def _slow_analysis():
    """
    Yahoo'dan 15 dk'da bir tam teknik analiz.
    RSI, Bollinger, momentum, skor → DEĞİŞTİR / DİKKAT sinyalleri.
    """
    try:
        import advisor
        import notifier

        state  = _load_state()
        active = state.get("active")
        if not active:
            log.info("Aktif pozisyon yok.")
            return

        sym = active["symbol"]
        log.info(f"Teknik analiz: {sym}...")

        import yfinance as yf
        import pandas as pd
        import numpy as np
        cfg = _load_cfg()

        raw = yf.download([f"{sym}.IS", "XU100.IS"],
                          period="90d", auto_adjust=True, progress=False, threads=True)

        def _get_df(s):
            ticker = f"{s}.IS"
            try:
                df = raw.xs(ticker, axis=1, level=1).dropna(how="all") \
                    if isinstance(raw.columns, pd.MultiIndex) else raw.dropna(how="all")
                return df if len(df) >= 20 else None
            except: return None

        df    = _get_df(sym)
        xu100 = _get_df("XU100")

        if df is None:
            log.warning(f"{sym} veri alınamadı.")
            return

        # Anlık fiyatı son satıra yansıt
        sys.path.insert(0, str(BASE))
        from price_reader import get_price
        live, kaynak = get_price(sym)
        if live and kaynak == "excel":
            df.iloc[-1, df.columns.get_loc("Close")] = live

        all_returns = {
            "r5":  {sym: advisor._pct(float(df["Close"].iloc[-1]), float(df["Close"].iloc[-6]))  if len(df)>5  else 0},
            "r20": {sym: advisor._pct(float(df["Close"].iloc[-1]), float(df["Close"].iloc[-21])) if len(df)>20 else 0},
            "r60": {sym: advisor._pct(float(df["Close"].iloc[-1]), float(df["Close"].iloc[-61])) if len(df)>60 else 0},
        }

        score = advisor.score_stock(sym, df, xu100, all_returns, cfg["sectors"])
        signal, msg, exit_pts = advisor.check_exit(active, score)

        log.info(f"{sym}: Skor={score['total_score']:.1f}/10  RSI={score['rsi']:.0f}"
                 f"  ÇıkışPuan={exit_pts}  Sinyal={signal}")

        # State güncelle
        state["active"]["last_score"] = score["total_score"]
        if not state["active"].get("target1"):
            state["active"]["target1"]  = score["target1"]
            state["active"]["target2"]  = score["target2"]
            state["active"]["stop_loss"] = state["active"].get("stop_loss") or score["stop_loss"]
        _save_state(state)

        # result.json güncelle
        try:
            from advisor import RESULT_PATH
            old = json.loads(RESULT_PATH.read_text(encoding="utf-8")) if RESULT_PATH.exists() else {}
            old["exit_signal"] = {
                "symbol": sym, "signal": signal, "exit_pts": exit_pts,
                "score_now": score["total_score"],
                "score_prev": active.get("last_score", score["total_score"]),
                "message": msg,
            }
            old["ts_str"] = datetime.now().strftime("%d.%m.%Y %H:%M")
            RESULT_PATH.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
            # Firebase güncelle
            try:
                import requests as _req
                _req.patch(
                    "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app/gridtracker/advisor.json",
                    json={"exit_signal": old["exit_signal"],
                          "ts_str": old["ts_str"]}, timeout=8)
            except: pass
        except: pass

        # Push: DİKKAT / ÇIK / DEĞİŞTİR
        if signal in ("DİKKAT", "ÇIK", "ACİL_ÇIK", "DEĞİŞTİR") and _should_send(sym, signal):
            new_pick, lot_info = _get_last_alternative(sym)
            notifier.send_exit_signal(
                signal, sym,
                active.get("last_score", score["total_score"]),
                score["total_score"], msg, new_pick, lot_info
            )
        elif signal == "DEVAM":
            # Sinyal düzeldiyse eski kayıtları temizle
            for s in ("DİKKAT", "ÇIK"):
                _reset_signal(sym, s)

    except Exception as e:
        log.error(f"Teknik analiz hatası: {e}", exc_info=True)


# ── ANA DÖNGÜ ─────────────────────────────────────────────────────────────────

def main():
    log.info("Monitor başlatıldı. Hızlı:5sn | Yavaş:15dk")
    print("[Monitor] Başlatıldı — Hızlı:5sn | Yavaş:15dk | Log:", log_path)

    last_slow = 0.0  # Son teknik analiz zamanı

    while True:
        try:
            if _is_market_open():
                # ── Hızlı kontrol: her 5 saniye ─────────────────────
                _fast_price_check()

                # ── Yavaş kontrol: her 15 dakika ─────────────────────
                if time.time() - last_slow >= SLOW_INTERVAL_MIN * 60:
                    threading.Thread(target=_slow_analysis, daemon=True).start()
                    last_slow = time.time()

                time.sleep(FAST_INTERVAL_SEC)

            else:
                now = datetime.now()
                log.info(f"Piyasa kapalı ({now.strftime('%H:%M')}). {OFF_HOURS_SLEEP_MIN}dk uyuyor.")
                time.sleep(OFF_HOURS_SLEEP_MIN * 60)

        except Exception as e:
            log.error(f"Ana döngü hatası: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
