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

# Spam koruması:
#  _sent          → olay bazlı (stop/hedef): 60 dk içinde tekrar yok
#  _last_state_sig → durum sinyali (DİKKAT/ÇIK/DEĞİŞTİR): SADECE sinyal
#                    değiştiğinde gönderilir. Aynı sinyal sürerse tekrar yok.
_sent = {}
_last_state_sig = {}   # {sym: en son gönderilen durum sinyali}
_sent_lock = threading.Lock()

# ── Yardımcılar ───────────────────────────────────────────────────────────────

def _fp(v) -> str:
    """Fiyatı 2 ondalık (kuruş) biçimler: 2.5 → '2.50', 64 → '64.00'."""
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)

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
    """Olay bazlı (stop/hedef): aynı olay 60 dk içinde tekrar gönderilmez."""
    key = f"{sym}:{signal}"
    with _sent_lock:
        last = _sent.get(key, 0)
        if time.time() - last < 3600:
            return False
        _sent[key] = time.time()
    return True

def _should_send_state(sym: str, signal: str) -> bool:
    """
    Durum sinyali (DİKKAT/ÇIK/DEĞİŞTİR): SADECE sinyal bir öncekinden
    farklıysa gönder. Aynı sinyal sürdükçe tekrar bildirim gelmez.
    (Örn: DİKKAT→DİKKAT susar, DİKKAT→ÇIK bildirir.)
    """
    with _sent_lock:
        if _last_state_sig.get(sym) == signal:
            return False
        _last_state_sig[sym] = signal
    return True

def _reset_state(sym: str):
    """Durum DEVAM'a döndüğünde — sonraki kötüleşme yeniden bildirilsin."""
    with _sent_lock:
        _last_state_sig.pop(sym, None)


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

        # ── Sermaye kartı için anlık fiyat + K/Z güncelle (result.json) ──
        # Her 5 sn'de bist_tracker.html Sermaye kartı güncel kalsın.
        _update_tracker_price(price, entry, qty)

    except Exception as e:
        log.error(f"Hızlı kontrol hatası: {e}")


def _update_tracker_price(price, entry, qty):
    """result.json'daki tracker bloğunu anlık fiyat + K/Z ile günceller."""
    try:
        from advisor import RESULT_PATH
        if not RESULT_PATH.exists():
            return
        d = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        tr = d.get("tracker")
        if not tr or not tr.get("active_symbol"):
            return
        avg = tr.get("avg_cost") or entry or 0
        open_qty = tr.get("open_qty") or tr.get("total_qty") or qty or 0
        tr["current_price"]  = round(price, 4)
        if avg > 0 and open_qty > 0:
            tr["unrealized_pnl"] = round((price - avg) * open_qty, 2)
            tr["unrealized_pct"] = round((price - avg) / avg * 100, 2)
        d["tracker"] = tr
        RESULT_PATH.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        # Firebase'e de yaz
        try:
            import requests as _req
            _req.patch(
                "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app/gridtracker/advisor/tracker.json",
                json={"current_price": tr["current_price"],
                      "unrealized_pnl": tr.get("unrealized_pnl", 0),
                      "unrealized_pct": tr.get("unrealized_pct", 0)},
                timeout=6)
        except:
            pass
    except Exception:
        pass


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

        # Push: DİKKAT / ÇIK / DEĞİŞTİR — SADECE sinyal değiştiğinde
        # (aynı sinyal sürdükçe saat başı tekrar bildirim GÖNDERİLMEZ)
        if signal in ("DİKKAT", "ÇIK", "ACİL_ÇIK", "DEĞİŞTİR") and _should_send_state(sym, signal):
            new_pick, lot_info = _get_last_alternative(sym)
            notifier.send_exit_signal(
                signal, sym,
                active.get("last_score", score["total_score"]),
                score["total_score"], msg, new_pick, lot_info
            )
        elif signal == "DEVAM":
            # Durum düzeldi — sonraki kötüleşme yeniden bildirilsin
            _reset_state(sym)

    except Exception as e:
        log.error(f"Teknik analiz hatası: {e}", exc_info=True)


# ── ANA DÖNGÜ ─────────────────────────────────────────────────────────────────

def _sync_position():
    """
    OTOMATİK POZİSYON TAKİBİ — 1.xlsx'i izleyip pozisyon değişimini yakalar.
      1. Aktif pozisyon tamamen satıldıysa → gerçekleşen karı history'ye ekle,
         active=null yap, bildirim gönder.
      2. Aktif pozisyon yokken bekleyen hisse (pending_buy) alındıysa →
         active = yeni hisse (maliyet/lot 1.xlsx'ten), bildirim gönder.
    """
    try:
        import notifier
        from tracker import _read_excel, COMM_RATE
        state = _load_state()
        active = state.get("active")

        # ── 1. AKTİF POZİSYON KAPANDI MI? ───────────────────────────────
        if active:
            sym = active["symbol"]
            buys, sells = _read_excel(sym)
            if buys:
                total_qty = sum(b["execQty"] for b in buys)
                avg_cost  = (sum(b["execAmount"] + b["commission"] for b in buys)
                             / total_qty) if total_qty else 0
            else:
                total_qty = active.get("qty", 0)
                avg_cost  = active.get("entry_price", 0.0)
            sold_qty    = sum(s["execQty"] for s in sells)
            open_qty    = total_qty - sold_qty

            if total_qty > 0 and open_qty <= 0 and sold_qty > 0:
                # Pozisyon tamamen kapandı → kar hesapla, history'ye ekle
                sell_amount = sum(s["execAmount"] - s["commission"] for s in sells)
                pnl_tl  = sell_amount - (avg_cost * sold_qty)
                pnl_pct = (pnl_tl / (avg_cost * sold_qty) * 100) if avg_cost and sold_qty else 0
                exit_px = sell_amount / sold_qty if sold_qty else 0

                rec = {
                    "symbol":     sym,
                    "entry_date": active.get("entry_date", ""),
                    "exit_date":  datetime.now().strftime("%Y-%m-%d"),
                    "entry_price": round(avg_cost, 4),
                    "exit_price":  round(exit_px, 4),
                    "qty":        sold_qty,
                    "pnl_tl":     round(pnl_tl, 2),
                    "pnl_pct":    round(pnl_pct, 2),
                    "exit_reason": "Manuel satış (sistem algıladı)",
                }
                state.setdefault("history", []).append(rec)
                state["active"] = None
                _save_state(state)
                log.info(f"POZİSYON KAPANDI: {sym} | K/Z: {pnl_tl:+.0f} TL ({pnl_pct:+.1f}%)")
                notifier._send(
                    f"✅ {sym} SATILDI",
                    f"Pozisyon kapandı.\n"
                    f"Giriş: {avg_cost:.2f} → Çıkış: {exit_px:.2f} TL\n"
                    f"Kâr/Zarar: {pnl_tl:+,.0f} TL ({pnl_pct:+.1f}%)".replace(",", "."),
                    tags="white_check_mark",
                )
                # Kapanış sonrası: yeni hisse arama bir sonraki döngüde
                return

        # ── 2. YENİ POZİSYON AÇILDI MI? (pending_buy alındı mı) ─────────
        if not state.get("active"):
            pending = state.get("pending_buy")
            if pending:
                psym = pending.get("symbol", "")
                pbuys, psells = _read_excel(psym)
                # Bugün net alım var mı?
                today = datetime.now().strftime("%Y-%m-%d")
                today_buys = [b for b in pbuys if b.get("date", "").startswith(today)]
                if today_buys:
                    tot_qty  = sum(b["execQty"] for b in pbuys)
                    sold     = sum(s["execQty"] for s in psells)
                    net_qty  = tot_qty - sold
                    if net_qty > 0:
                        avg = (sum(b["execAmount"] + b["commission"] for b in pbuys)
                               / tot_qty) if tot_qty else 0
                        state["active"] = {
                            "symbol":     psym,
                            "entry_date": today,
                            "entry_price": round(avg, 4),
                            "qty":        net_qty,
                            "stop_loss":  pending.get("stop_loss", 0),
                            "target1":    pending.get("target1", 0),
                            "target2":    pending.get("target2", 0),
                            "last_score": pending.get("score", 0),
                            "timeframe":  pending.get("timeframe", ""),
                        }
                        state["pending_buy"] = None
                        _save_state(state)
                        log.info(f"YENİ POZİSYON: {psym} | {net_qty} lot @ {avg:.2f}")
                        notifier._send(
                            f"🟢 {psym} ALINDI",
                            f"Yeni pozisyon açıldı.\n"
                            f"Maliyet: {avg:.2f} TL | {net_qty:,} lot\n"
                            f"Stop: {pending.get('stop_loss',0):.2f} | "
                            f"Hedef: {pending.get('target1',0):.2f}".replace(",", "."),
                            tags="green_circle",
                        )
    except Exception as e:
        log.error(f"Pozisyon senkron hatası: {e}", exc_info=True)


def _check_pending_entry():
    """
    Bekleyen öneri (pending_buy) fiyat KAÇTI mı? Kaçtıysa HEMEN sıradaki
    uygun öneriye geç (advisor_result.json top_picks'ten, giriş bölgesinde
    olan ilk hisse). Kullanıcı yarını beklemez — anında yeni hedef alır.
    """
    try:
        import notifier
        sys.path.insert(0, str(BASE))
        from price_reader import get_price

        state = _load_state()
        if state.get("active"):
            return  # zaten pozisyon var, öneri takibi yok
        pending = state.get("pending_buy")
        if not pending:
            return

        psym = pending.get("symbol", "")
        ehigh = pending.get("entry_high", 0)
        if not psym or not ehigh:
            return

        price, _src = get_price(psym)
        if not price:
            return

        # Fiyat giriş bölgesinin %1.5 üstüne çıktıysa "kaçtı" say
        if price <= ehigh * 1.015:
            return  # hâlâ girilebilir, dokunma

        # ── KAÇTI → advisor_result.json'dan sıradaki uygun öneriyi bul ──
        from advisor import RESULT_PATH
        d = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        picks = d.get("top_picks", [])
        lot_info = d.get("lot_info", {})

        new_pick = None
        for p in picks:
            if p["symbol"] == psym:
                continue
            ez = p.get("entry_zone", {})
            cur, _ = get_price(p["symbol"])
            # Fiyatı hâlâ giriş bölgesinde (veya altında) olan ilk aday
            if cur and ez.get("high") and cur <= ez["high"] * 1.015:
                new_pick = p
                break

        if not _should_send_state(psym, "KACTI"):
            return  # bu sembol için zaten bildirildi

        if new_pick:
            # pending'i yeni öneriyle güncelle
            state["pending_buy"] = {
                "symbol":     new_pick["symbol"],
                "stop_loss":  new_pick.get("stop_loss", 0),
                "target1":    new_pick.get("target1", 0),
                "target2":    new_pick.get("target2", 0),
                "score":      new_pick.get("total_score", 0),
                "timeframe":  new_pick.get("timeframe", ""),
                "entry_low":  new_pick.get("entry_zone", {}).get("low", 0),
                "entry_high": new_pick.get("entry_zone", {}).get("high", 0),
            }
            _save_state(state)
            _reset_state(new_pick["symbol"])  # yeni sembol için kaçtı bildirimi açılsın
            log.info(f"{psym} kaçtı ({price:.2f}>{ehigh:.2f}) → yeni öneri: {new_pick['symbol']}")
            lines = notifier._new_pick_lines(new_pick, lot_info, baslik="✅ YENİ ÖNERİ")
            notifier._send(
                f"🔄 {psym} kaçtı — yeni hedef",
                f"{psym} giriş bölgesini aştı ({_fp(price)} > {_fp(ehigh)}).\n"
                + "\n".join(lines[1:]),
                priority="high", tags="arrows_counterclockwise")
        else:
            # Hiçbir öneri uygun değil
            log.info(f"{psym} kaçtı, sıradaki uygun öneri yok.")
            notifier._send(
                f"🔴 {psym} kaçtı",
                f"{psym} giriş bölgesini aştı ({_fp(price)} > {_fp(ehigh)}).\n"
                f"Şu an uygun fiyatta başka aday yok. Akşam yeni analiz yapılacak.",
                priority="high", tags="warning")
    except Exception as e:
        log.error(f"Pending kontrol hatası: {e}")


def main():
    log.info("Monitor başlatıldı. Hızlı:5sn | Yavaş:15dk | PendingKontrol:30sn")
    print("[Monitor] Başlatıldı — Hızlı:5sn | Yavaş:15dk | Log:", log_path)

    last_slow    = 0.0  # Son teknik analiz zamanı
    last_pending = 0.0  # Son pending (öneri kaçtı mı) kontrolü
    # NOT: Pozisyon senkronu (sat/al algılama) burada YAPILMAZ — 1.xlsx akşam
    # 18:35'te oluşuyor, gün içi güncel değil. Senkron advisor.py --run içinde
    # (evening_automation, 1.xlsx hazır olduktan sonra) yapılır.

    while True:
        try:
            if _is_market_open():
                # ── Hızlı kontrol: her 5 saniye ─────────────────────
                _fast_price_check()

                # ── Öneri kaçtı mı: her 30 saniye ───────────────────
                if time.time() - last_pending >= 30:
                    threading.Thread(target=_check_pending_entry, daemon=True).start()
                    last_pending = time.time()

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
