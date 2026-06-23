"""
monitor.pyw — İki katmanlı arka plan servisi

Hızlı döngü  (5 sn)  : Excel'den anlık fiyat → stop/hedef → ANINDA bildirim
Yavaş döngü  (15 dk) : Yahoo teknik analiz → RSI/Bollinger/skor → sinyal

Piyasa saatleri: 10:00 – 18:20 (BIST)
"""
import json, sys, time, logging, threading
from datetime import datetime, time as dtime, timedelta
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

# Firebase kullanıcı komut kanalı (HTML "Sattım"/"Aldım" butonları buraya yazar)
_FB_BASE       = "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app"
_FB_USERACTION = _FB_BASE + "/gridtracker/advisor/userAction.json"

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


def _record_recommended(state: dict, symbol: str, pick: dict = None):
    """Gün içi önerilen sembolü kaydet — akşam senkronu Excel'de arayıp K/Z işler."""
    if not symbol:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    # Son 7 günün önerilerini tut (ertesi gün alımlar için kayıt düşmesin)
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recs = state.setdefault("recommended_today", [])
    recs[:] = [r for r in recs if isinstance(r, dict) and r.get("date", "") >= cutoff]
    if any(r.get("symbol") == symbol for r in recs):
        return
    e = {"symbol": symbol, "date": today, "entry_date": today}
    if pick:
        e.update({"stop_loss": pick.get("stop_loss", 0), "hard_stop": pick.get("hard_stop", 0),
                  "target1": pick.get("target1", 0), "target2": pick.get("target2", 0),
                  "timeframe": pick.get("timeframe", ""), "score": pick.get("total_score", 0)})
    recs.append(e)


def _push_stop_to_card(stop, hard):
    """Trailing ile yükselen stop'u Firebase'e yaz → danışman kartı anında göstersin."""
    try:
        import requests as _req
        _fb = "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app/gridtracker/advisor"
        _req.patch(f"{_fb}/tracker.json", json={"stop_loss": stop, "hard_stop": hard}, timeout=6)
        _req.patch(f"{_fb}/active_pick.json", json={"stop_loss": stop, "hard_stop": hard}, timeout=6)
        # result.json (PC kartı) da güncellensin
        from advisor import RESULT_PATH
        if RESULT_PATH.exists():
            d = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
            if d.get("tracker"): d["tracker"]["stop_loss"] = stop; d["tracker"]["hard_stop"] = hard
            if d.get("active_pick"): d["active_pick"]["stop_loss"] = stop; d["active_pick"]["hard_stop"] = hard
            RESULT_PATH.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log.debug(f"_push_stop_to_card hatası: {e}")


def _push_tracker_after_close(state: dict):
    """Pozisyon kapanınca kartı ANINDA tazele: tracker'ı yeniden hesapla,
    result.json + Firebase'e yaz (active_pick temizlenir)."""
    try:
        from tracker import track
        from advisor import RESULT_PATH
        tr = track(state)
        if RESULT_PATH.exists():
            d = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
            d["tracker"] = tr
            d["active_pick"] = None
            RESULT_PATH.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        import requests as _req
        _fb = "https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app/gridtracker/advisor"
        _req.put(f"{_fb}/tracker.json", json=tr, timeout=6)
        _req.put(f"{_fb}/active_pick.json", data="null", timeout=6)  # json=None gövde göndermez
    except Exception as e:
        log.debug(f"tracker push (kapanış) hatası: {e}")

def _load_cfg() -> dict:
    return json.loads((BASE / "config.json").read_text(encoding="utf-8"))

def _is_market_open() -> bool:
    now = datetime.now()
    if now.weekday() not in WEEKDAYS: return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE

def _should_send(sym: str, signal: str, cooldown: int = 3600) -> bool:
    """Olay bazlı: aynı olay cooldown sn içinde tekrar gönderilmez (varsayılan 60 dk)."""
    key = f"{sym}:{signal}"
    with _sent_lock:
        last = _sent.get(key, 0)
        if time.time() - last < cooldown:
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


# Saatlik kapanış kontrolü için throttle (yfinance'ı 5 sn'de bir çağırmamak için)
_hourly_cache = {}  # sym -> (timestamp, result)
_HOURLY_TTL   = 180  # saniye

def _hourly_closed_below(sym: str, level: float):
    """
    Son TAMAMLANMIŞ saatlik mumun kapanışı `level` altında mı?
      True  → saatlik mum stop altında kapandı (gerçek kırılım)
      False → kapanmadı (fitil olabilir, bekle)
      None  → veri alınamadı (güvenli taraf: bekle)
    Oluşmakta olan (yarım) saatlik mum hariç tutulur — fitil avını eler.
    180 sn cache ile yfinance yükü sınırlanır.
    """
    try:
        now = time.time()
        cached = _hourly_cache.get(sym)
        if cached and (now - cached[0]) < _HOURLY_TTL:
            base_close = cached[1]
        else:
            import yfinance as yf
            df = yf.Ticker(sym + ".IS").history(period="3d", interval="60m",
                                                auto_adjust=True)
            if df is None or len(df) < 2:
                return None
            last_ts = df.index[-1].to_pydatetime()
            tznow   = datetime.now(last_ts.tzinfo) if last_ts.tzinfo else datetime.now()
            # Son bar bu saat içindeyse henüz kapanmadı → bir önceki tamamlanmış mumu al
            if last_ts.hour == tznow.hour and last_ts.date() == tznow.date():
                if len(df) < 2:
                    return None
                base_close = float(df["Close"].iloc[-2])
            else:
                base_close = float(df["Close"].iloc[-1])
            _hourly_cache[sym] = (now, base_close)
        return base_close <= level
    except Exception as e:
        log.debug(f"_hourly_closed_below({sym}): {e}")
        return None


# ── HIZLI DÖNGÜ: Anlık fiyat → Stop / Hedef kontrolü ────────────────────────

# ── GÜN İÇİ MUM BİRİKTİRME (DDE 5 sn örneklerinden 5 dk barlar) ─────────────
# Yeni veri kaynağı YOK: zaten 5 sn'de bir okunan DDE fiyatından kendi gün-içi
# barlarımızı üretiriz. Günlük barların göremediği saat-içi momentum (erken
# çıkış / fırsat alımı zamanlaması) buradan ölçülür.
_IBARS_PATH  = BASE / "intraday_bars.json"
_ibars       = None
_ibars_saved = 0.0


def _ibar_add(sym: str, price: float):
    """5 dk'lık OHLC barına örnek ekle. Periyodik diske yazar (restart dayanıklı)."""
    global _ibars, _ibars_saved
    try:
        if _ibars is None:
            try:
                _ibars = json.loads(_IBARS_PATH.read_text(encoding="utf-8"))
            except Exception:
                _ibars = {}
        today  = datetime.now().strftime("%Y-%m-%d")
        bucket = int(time.time() // 300) * 300
        rec = _ibars.get(sym)
        if not rec or rec.get("date") != today:
            rec = {"date": today, "bars": []}
            _ibars[sym] = rec
        bars = rec["bars"]
        if bars and bars[-1][0] == bucket:
            b = bars[-1]
            b[2] = max(b[2], price); b[3] = min(b[3], price); b[4] = price
        else:
            bars.append([bucket, price, price, price, price])
            del bars[:-120]   # en fazla 120 bar (10 saat) tut
        if time.time() - _ibars_saved > 300:
            _ibars_saved = time.time()
            _IBARS_PATH.write_text(json.dumps(_ibars), encoding="utf-8")
    except Exception:
        pass


def _intraday_chg(sym: str, minutes: int = 30):
    """Son N dakikadaki % değişim (5 dk barlardan). Yeterli veri yoksa None."""
    try:
        rec = (_ibars or {}).get(sym)
        if not rec or rec.get("date") != datetime.now().strftime("%Y-%m-%d"):
            return None
        bars = rec["bars"]
        need = max(2, minutes // 5)
        if len(bars) < need:
            return None
        c_now, c_old = bars[-1][4], bars[-need][4]
        return (c_now / c_old - 1) * 100 if c_old else None
    except Exception:
        return None


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
        # Felaket stopu: yoksa stop'un ~%1.5 altını kullan (acil intraday çıkış)
        hard  = active.get("hard_stop") or (round(stop * 0.985, 4) if stop else 0)
        h1    = active.get("target1", 0)
        h2    = active.get("target2", 0)
        entry = active.get("entry_price", 0)

        price, kaynak = get_price(sym)
        if not price:
            return

        # Gün içi bar biriktir (sadece CANLI DDE fiyatından — gecikmeli Yahoo karışmasın)
        if kaynak == "excel":
            _ibar_add(sym, price)

        # P&L hesabı
        qty     = active.get("qty", 0)
        pnl_pct = ((price - entry) / entry * 100) if entry else 0
        pnl_tl  = (price - entry) * qty if (entry and qty) else 0

        # ── TRAILING STOP: fiyat yükseldikçe stop'u YUKARI çek (kâr kilitle) ──
        # Orijinal stop mesafesi kadar geriden takip eder; sadece yukarı hareket eder.
        # Stop anlamlı yükseldiğinde "çıkışını buna göre ayarla" bildirimi gönderir.
        if entry and stop and price > entry:
            est = active.get("entry_stop")
            # GÜVENLİK: entry_stop eksik VEYA girişin altında değilse (bozuk
            # bookkeeping — örn. mutabakat alanı düşürdüyse), mevcut stop'tan
            # değil, güvenli bir orijinal mesafeden türet. Aksi halde trail_dist
            # negatif olur ve stop fiyatın üstüne çıkıp sahte stop-out yapar.
            if est is None or est >= entry:
                # Mevcut stop girişin altındaysa onu kullan; değilse peak'ten türet
                if stop < entry:
                    est = stop
                else:
                    _pk = active.get("peak_price", entry) or entry
                    est = round(entry - max(0.01, _pk - stop), 4)
                active["entry_stop"] = est                       # orijinal stop (onarıldı)
            if active.get("entry_hard") is None or active.get("entry_hard") >= entry:
                active["entry_hard"] = round(est - max(0.01, est - hard), 4) if hard < est else round(est * 0.96, 4)
            trail_dist = entry - est                             # orijinal mesafe (>0 garanti)
            gap        = est - active.get("entry_hard", hard)    # stop↔felaket farkı
            peak       = max(active.get("peak_price", entry) or entry, price)
            new_stop   = round(peak - trail_dist, 4)
            if new_stop > stop + max(0.01, price * 0.001):       # anlamlı yukarı (≥%0.1)
                old_stop = stop
                stop = new_stop
                hard = round(new_stop - gap, 4)
                active["stop_loss"] = stop
                active["hard_stop"] = hard
                active["peak_price"] = peak
                _save_state(state)
                log.info(f"TRAIL: {sym} stop {old_stop}→{stop} (peak {_fp(peak)})")
                # Kart anında güncellensin (sessiz — ayrı bildirim yok,
                # stop kırılınca zaten ÇIK bildirimi gelecek)
                _push_stop_to_card(stop, hard)
            elif peak > (active.get("peak_price", entry) or entry) + price * 0.0015:
                active["peak_price"] = peak                       # peak ilerledi, kaydet
                _save_state(state)

        # ── FELAKET STOPU: stop'un belirgin altı → ANINDA ÇIK (kapanış bekleme) ──
        if hard and price <= hard:
            if _should_send(sym, "ACİL_ÇIK"):
                log.warning(f"FELAKET STOP! {sym} {_fp(price)} <= {_fp(hard)}")
                new_pick, lot_info = _get_last_alternative(sym)
                notifier.send_exit_signal(
                    "ACİL_ÇIK", sym,
                    active.get("last_score", 0),
                    active.get("last_score", 0),
                    f"⚡ SERT DÜŞÜŞ! {_fp(price)} ₺ ≤ felaket stop {_fp(hard)} ₺ "
                    f"({pnl_pct:+.1f}%) — KAPANIŞ BEKLEME, HEMEN ÇIK!",
                    new_pick, lot_info
                )
            return

        # ── STOP BÖLGESİ: fiyat stop altında ama felaket değil → KAPANIŞ BARINI BEKLE ──
        if stop and price <= stop:
            closed_below = _hourly_closed_below(sym, stop)
            if closed_below is True:
                # Saatlik mum stop altında KAPANDI → gerçek kırılım, çık
                if _should_send(sym, "ACİL_ÇIK"):
                    log.warning(f"SAATLİK KAPANIŞ STOP ALTINDA! {sym} {_fp(price)} <= {_fp(stop)}")
                    new_pick, lot_info = _get_last_alternative(sym)
                    notifier.send_exit_signal(
                        "ACİL_ÇIK", sym,
                        active.get("last_score", 0),
                        active.get("last_score", 0),
                        f"Saatlik mum stop altında KAPANDI ({_fp(stop)} ₺) — "
                        f"gerçek kırılım, ÇIK ({pnl_pct:+.1f}%)",
                        new_pick, lot_info
                    )
            else:
                # Henüz kapanış onayı yok → fitil olabilir, panik yok: BEKLE
                if _should_send(sym, "STOP_TEST"):
                    log.info(f"{sym} stop bölgesinde ({_fp(price)} <= {_fp(stop)}) — kapanış bekleniyor")
                    notifier._send(
                        f"⏳ {sym} — KAPANIŞ BARINI BEKLE..!!",
                        f"Fiyat {_fp(price)} ₺, stop seviyesi {_fp(stop)} ₺ altında.\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"⚠️ HENÜZ ÇIKMA — bu bir fitil olabilir.\n"
                        f"Saatlik mum stop altında KAPANIRSA çıkış sinyali gelecek.\n"
                        f"Felaket seviyesi: {_fp(hard)} ₺ (buraya inerse anında çık).\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"Anlık K/Z: {pnl_pct:+.1f}%",
                        priority="high", tags="hourglass")
            return

        # ── HEDEF: 1. hedefe ulaşıldı → SADECE HATIRLAT (otomatik kapatma YOK) ──
        # Kullanıcı tercihi: pozisyon yalnızca "✅ Sattım" butonuna basınca kapanır.
        # Burada fiyat hedefe değince satış hatırlatması gönderilir; gerçek kapanış
        # ve sıradaki öneri, kullanıcı onayı (_do_user_sold) ile tetiklenir.
        if h1 and price >= h1:
            if _should_send(sym, "TARGET_REMIND"):
                kar = (price - entry) * qty if (entry and qty) else 0
                log.info(f"1. HEDEF ulaşıldı: {sym} {_fp(price)} (+{kar:.0f} TL) — onay bekleniyor")
                notifier._send(
                    f"🎯 {sym} 1. HEDEF — SATIŞ ZAMANI",
                    f"Fiyat: {_fp(price)} TL  ({pnl_pct:+.1f}%)\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"➤ {qty:,} LOT'U SAT (tam çıkış, kârı al)\n".replace(",", ".") +
                    f"Tahmini kâr: +{kar:,.0f} TL  💰\n".replace(",", ".") +
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Sattıktan sonra bildirimdeki SATTIM butonuna bas → "
                    f"sıradaki öneri anında gelsin.",
                    priority="urgent", tags="dart", alert=True,
                    actions=notifier.action_sold(sym))
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


# ── MANUEL ONAY KOMUTLARI (HTML "Sattım"/"Aldım" → Firebase → burada işlenir) ──

def _clear_user_action():
    """İşlenen komutu Firebase'den temizle (null yaz).
    NOT: requests'te json=None gövde GÖNDERMEZ; Firebase'e literal null yazmak
    için data='null' kullanılmalı (aksi halde node silinmez)."""
    try:
        import requests as _req
        _req.put(_FB_USERACTION, data="null", timeout=6)
    except Exception as e:
        log.debug(f"_clear_user_action: {e}")


def _find_pick(sym: str):
    """advisor_result.json'dan verilen sembolün öneri detayını + lot_info döner."""
    try:
        from advisor import RESULT_PATH
        d = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        for p in d.get("top_picks", []):
            if p.get("symbol") == sym:
                return p, d.get("lot_info", {})
        ap = d.get("active_pick")
        if ap and ap.get("symbol") == sym:
            return ap, d.get("lot_info", {})
    except Exception:
        pass
    return None, {}


def _do_user_sold(state: dict, symbol: str):
    """Kullanıcı 'Sattım' dedi → aktif pozisyonu kapat (tahmini), sıradaki öneriyi hazırla.
    Gerçek K/Z akşam 1.xlsx senkronunda düzeltilir (provisional)."""
    import notifier
    sys.path.insert(0, str(BASE))
    from price_reader import get_price

    active = state.get("active")
    if not active:
        log.info("Sattım: aktif pozisyon yok, atlanıyor.")
        return
    # BAYAT BUTON KORUMASI: komut belirli bir sembol içinse ve aktif pozisyon
    # farklıysa (eski bildirimin butonu) → işlem yapma.
    if symbol and active.get("symbol") != symbol:
        log.info(f"Sattım: komut {symbol} için ama aktif {active.get('symbol')} — bayat buton, atlandı.")
        return
    sym   = active["symbol"]
    entry = active.get("entry_price", 0)
    qty   = active.get("qty", 0)
    price, _src = get_price(sym)
    exit_px = price or active.get("target1") or entry
    kar     = (exit_px - entry) * qty if (entry and qty) else 0
    pnl_pct = ((exit_px - entry) / entry * 100) if entry else 0

    state.setdefault("history", []).append({
        "symbol": sym,
        "entry_date": active.get("entry_date", ""),
        "exit_date":  datetime.now().strftime("%Y-%m-%d"),
        "entry_price": round(entry, 4),
        "exit_price":  round(exit_px, 4),
        "qty": qty,
        "pnl_tl":  round(kar, 2),
        "pnl_pct": round(pnl_pct, 2),
        "exit_reason": "Manuel — Sattım butonu (tahmini)",
        "provisional": True,
    })
    state["active"] = None

    # SATTIĞIN AN TAZE ÖNERİ: sıradaki hisseyi eski (saatlerce önceki) top_picks'ten
    # değil, ŞİMDİ yeniden üretilen analizden seç. ~30-60 sn sürer ama satıştan
    # sonra güncel öneri kritik. Başarısız olursa mevcut top_picks'e düşer (graceful).
    if _is_market_open():
        try:
            import advisor
            log.info("Sattım sonrası öneriler tazeleniyor (canlı analiz)...")
            advisor.run_analysis(refresh_only=True, quiet=True)
        except Exception as e:
            log.warning(f"Satış sonrası refresh başarısız, mevcut öneriler kullanılacak: {e}")

    new_pick, lot_info = _get_last_alternative(sym)
    if new_pick:
        state["pending_buy"] = {
            "symbol":     new_pick["symbol"],
            "stop_loss":  new_pick.get("stop_loss", 0),
            "hard_stop":  new_pick.get("hard_stop", 0),
            "target1":    new_pick.get("target1", 0),
            "target2":    new_pick.get("target2", 0),
            "score":      new_pick.get("total_score", 0),
            "timeframe":  new_pick.get("timeframe", ""),
            "entry_low":  new_pick.get("entry_zone", {}).get("low", 0),
            "entry_high": new_pick.get("entry_zone", {}).get("high", 0),
        }
        _record_recommended(state, new_pick["symbol"], new_pick)
    else:
        state["pending_buy"] = None

    _save_state(state)
    _push_tracker_after_close(state)
    log.info(f"MANUEL SATIŞ: {sym} {_fp(exit_px)} (+{kar:.0f} TL) → "
             f"yeni öneri: {new_pick['symbol'] if new_pick else 'yok'}")

    body = (f"✅ {sym} kapandı (tahmini).\n"
            f"Çıkış: {_fp(exit_px)} TL  ({pnl_pct:+.1f}%)\n"
            f"Tahmini kâr: {kar:+,.0f} TL".replace(",", "."))
    if new_pick:
        lines = notifier._new_pick_lines(new_pick, lot_info, baslik="✅ SIRADAKİ ÖNERİ")
        body += "\n" + "\n".join(lines[1:])
    notifier._send(f"✅ {sym} SATILDI — sıradaki hazır", body,
                   priority="high", tags="white_check_mark",
                   actions=(notifier.action_bought(new_pick["symbol"]) if new_pick else ""))


def _do_user_bought(state: dict, symbol: str):
    """Kullanıcı 'Aldım' dedi → öneriyi aktif pozisyon yap (tahmini maliyet = canlı fiyat).
    Gerçek maliyet/lot akşam 1.xlsx senkronunda düzeltilir."""
    import notifier
    sys.path.insert(0, str(BASE))
    from price_reader import get_price

    pending = state.get("pending_buy") or {}
    sym = symbol or pending.get("symbol")
    if not sym:
        log.info("Aldım: sembol yok, atlanıyor.")
        return
    pick, lot_info = _find_pick(sym)
    li  = (lot_info or {}).get(sym, {})
    qty = li.get("lots_main") or li.get("lots") or 0
    price, _src = get_price(sym)
    entry = price or (pick or {}).get("price") or 0
    # stop/hedef: pending eşleşiyorsa ondan, yoksa öneri detayından
    src = pending if pending.get("symbol") == sym else (pick or {})

    state["active"] = {
        "symbol":      sym,
        "entry_date":  datetime.now().strftime("%Y-%m-%d"),
        "entry_price": round(entry, 4),
        "qty":         qty,
        "stop_loss":   src.get("stop_loss", 0),
        "hard_stop":   src.get("hard_stop", 0),
        "target1":     src.get("target1", 0),
        "target2":     src.get("target2", 0),
        "last_score":  src.get("score", src.get("total_score", 0)),
        "timeframe":   src.get("timeframe", ""),
    }
    state["pending_buy"] = None
    _save_state(state)
    log.info(f"MANUEL ALIŞ: {sym} {qty} lot @ {_fp(entry)}")

    # Kartı anında aktif pozisyon moduna geçir: tracker + active_pick + sinyal Firebase'e
    # İlk sinyal "DEVAM" yazılır (yeni alındı, tutmaya devam) → kart "BEKLENİYOR"
    # yerine "DEVAM" gösterir. Gerçek sinyal birazdan _slow_analysis ile gelir.
    _init_score = src.get("score", src.get("total_score", 0)) or 0
    init_es = {"symbol": sym, "signal": "DEVAM", "exit_pts": 0,
               "score_now": _init_score, "score_prev": _init_score, "message": ""}
    try:
        from tracker import track
        from advisor import RESULT_PATH
        tr        = track(state)
        pick_data = {**pick, "rank": 0} if pick else None
        if RESULT_PATH.exists():
            d = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
            d["tracker"]     = tr
            d["active_pick"] = pick_data
            d["exit_signal"] = init_es
            RESULT_PATH.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        import requests as _req
        _fb = _FB_BASE + "/gridtracker/advisor"
        _req.put(_fb + "/tracker.json", json=tr, timeout=6)
        _req.patch(_fb + ".json", json={"exit_signal": init_es}, timeout=6)
        if pick_data is None:
            _req.put(_fb + "/active_pick.json", data="null", timeout=6)
        else:
            _req.put(_fb + "/active_pick.json", json=pick_data, timeout=6)
    except Exception as e:
        log.debug(f"bought tracker push: {e}")

    # ── GÜVENLİK AĞI: üst banttan alım uyarısı ───────────────────────────────
    # Kullanıcı şartı: üst banttan ALDIRMA. Öneri filtresi bb<0.70 ama fiyat
    # öneri ile alım arası bandın üstüne kaçmış olabilir → alım anındaki güncel
    # bb'yi kontrol et; üst banttaysa (≥0.80) ACİL uyar (çıkışa hazır ol).
    _bb_warn = ""
    try:
        from advisor import RESULT_PATH as _RP
        if _RP.exists():
            _st = (json.loads(_RP.read_text(encoding="utf-8")).get("score_table") or {})
            _bb = (_st.get(sym) or {}).get("bb")
            if _bb is not None and _bb >= 0.80:
                _bb_warn = (f"\n⚠️ DİKKAT: {sym} şu an Bollinger ÜST BANDINDA "
                            f"(bb {_bb:.2f}) — tepe riski. Düşerse stop'a sıkı uy, "
                            f"ısrar etme.")
    except Exception:
        pass

    notifier._send(
        f"🟢 {sym} ALINDI",
        f"Pozisyon açıldı (tahmini).\n"
        f"Maliyet: {_fp(entry)} TL | {qty:,} lot\n".replace(",", ".") +
        f"Stop: {_fp(state['active']['stop_loss'])} | Hedef: {_fp(state['active']['target1'])} TL\n"
        f"Akşam gerçek rakamlarla güncellenecek." + _bb_warn,
        priority="high", tags="green_circle",
        alert=bool(_bb_warn))

    # Gerçek sinyali HEMEN hesapla (sadece bu hisse + endeks indirilir, ~5 sn)
    # → kart "DEVAM/DİKKAT" doğru sinyali 15 dk beklemeden gösterir.
    if _is_market_open():
        threading.Thread(target=_slow_analysis, daemon=True).start()


def _do_set_capital(state: dict, capital):
    """Kullanıcı sermayeyi güncelledi → state.json'a yaz, Firebase'i tazele.
    (HTML yerel sunucuya değil Firebase'e yazdığı için telefonda da çalışır.)"""
    try:
        cap = float(capital or 0)
    except (TypeError, ValueError):
        cap = 0
    if cap <= 0:
        log.info("set_capital: geçersiz değer, atlandı.")
        _save_state(state)   # last_action_id yine de yazılsın (komut işlendi sayılsın)
        return
    state["capital"] = cap
    _save_state(state)
    log.info(f"SERMAYE GÜNCELLENDİ: {cap:,.0f} TL".replace(",", "."))
    # Firebase advisor/capital'i güncelle (kart anında doğru göstersin)
    try:
        import requests as _req
        _req.patch(_FB_BASE + "/gridtracker/advisor.json",
                   json={"capital": cap}, timeout=6)
    except Exception as e:
        log.debug(f"set_capital firebase patch: {e}")
    # LOTLARI YENİ SERMAYEYE GÖRE yeniden hesapla — arka planda (~30-60 sn).
    # run_analysis(refresh_only) state.json'daki yeni capital'i okur, top_picks
    # lot_info'sunu yeni sermayeye göre üretip Firebase'e yazar.
    def _recalc_lots():
        try:
            import advisor
            advisor.run_analysis(refresh_only=True, quiet=True)
            log.info("Sermaye sonrası lotlar yeniden hesaplandı.")
        except Exception as e:
            log.debug(f"sermaye sonrası lot recalc: {e}")
    threading.Thread(target=_recalc_lots, daemon=True).start()


def _process_user_action():
    """Firebase'deki kullanıcı komutunu (Sattım/Aldım/SetCapital) işler — idempotent (id ile)."""
    import requests as _req
    try:
        r   = _req.get(_FB_USERACTION, timeout=8)
        act = r.json()
    except Exception:
        return
    if not act or not isinstance(act, dict):
        return
    aid    = act.get("id")
    action = act.get("action")
    symbol = (act.get("symbol") or "").upper()
    if not aid or not action:
        _clear_user_action()
        return

    state = _load_state()
    if state.get("last_action_id") == aid:
        _clear_user_action()   # zaten işlenmiş, sadece temizle
        return

    state["last_action_id"] = aid   # _do_* save edince birlikte yazılır
    try:
        if action == "sold":
            _do_user_sold(state, symbol)
        elif action == "bought":
            _do_user_bought(state, symbol)
        elif action == "set_capital":
            _do_set_capital(state, act.get("capital"))
        else:
            _save_state(state)
    except Exception as e:
        log.error(f"Kullanıcı komutu ({action}) hatası: {e}", exc_info=True)
        return
    _clear_user_action()


def _user_action_loop():
    """Kullanıcı komutlarını 7/24 her 4 sn'de bir Firebase'den kontrol eder."""
    while True:
        try:
            _process_user_action()
        except Exception as e:
            log.debug(f"_user_action_loop: {e}")
        time.sleep(4)


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

        # AŞAĞI yönlü erken bozulma dedektörü (vur-kaç: küçük zararla erken çık)
        # Gün içi ivme (DDE 5dk barlarından): günlük barların göremediği
        # saat-içi kırılmayı da hesaba kat.
        chg30 = _intraday_chg(sym, 30)
        ew_level, ew_msg, ew_pts = advisor.check_early_weakness(
            active, df, score, xu100, intraday_chg=chg30)

        # Nihai sinyal: check_exit ÇIK/ACİL/DEĞİŞTİR öncelikli; yoksa erken-zayıflama
        if signal in ("ÇIK", "ACİL_ÇIK", "DEĞİŞTİR"):
            final, final_msg = signal, msg
        elif ew_level == "ERKEN_ÇIK":
            final, final_msg = "ÇIK_ERKEN", ew_msg
        elif ew_level == "ZAYIFLAMA":
            final, final_msg = "DİKKAT", (ew_msg or msg)
        elif signal == "DİKKAT":
            final, final_msg = "DİKKAT", msg
        else:
            final, final_msg = "DEVAM", ""

        log.info(f"{sym}: Skor={score['total_score']:.1f}/10  RSI={score['rsi']:.0f}"
                 f"  ÇıkışPuan={exit_pts}  Zayıflama={ew_level}({ew_pts})"
                 f"  İvme30dk={f'{chg30:+.2f}%' if chg30 is not None else '—'}  Sinyal={final}")

        # State güncelle
        state["active"]["last_score"] = score["total_score"]
        if not state["active"].get("target1"):
            state["active"]["target1"]  = score["target1"]
            state["active"]["target2"]  = score["target2"]
            state["active"]["stop_loss"] = state["active"].get("stop_loss") or score["stop_loss"]
        _save_state(state)

        # Kartta gösterilecek etiket (ÇIK_ERKEN → "ERKEN ÇIK")
        disp_sig = "ERKEN ÇIK" if final == "ÇIK_ERKEN" else final

        # result.json güncelle
        try:
            from advisor import RESULT_PATH
            old = json.loads(RESULT_PATH.read_text(encoding="utf-8")) if RESULT_PATH.exists() else {}
            old["exit_signal"] = {
                "symbol": sym, "signal": disp_sig, "exit_pts": max(exit_pts, ew_pts),
                "score_now": score["total_score"],
                "score_prev": active.get("last_score", score["total_score"]),
                "message": final_msg,
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

        # Push — SADECE sinyal değiştiğinde (aynı sinyal sürdükçe tekrar yok)
        if final == "ÇIK_ERKEN":
            if _should_send_state(sym, "ÇIK_ERKEN"):
                new_pick, lot_info = _get_last_alternative(sym)
                lines = [
                    f"Skor: {score['total_score']:.1f}/10  |  RSI: {score['rsi']:.0f}",
                    f"Sebep: {ew_msg}",
                    "",
                    "📉 Yapı bozuluyor — stop'a varmadan, küçük zararla/kârla",
                    "çıkıp sıradaki fırsata geçmek için uygun an.",
                ]
                if new_pick:
                    lines += notifier._new_pick_lines(new_pick, lot_info)
                notifier._send(f"🟠 {sym} — ERKEN ÇIKIŞ — SAT", "\n".join(lines),
                               priority="urgent", tags="warning", alert=True,
                               actions=notifier.action_sold(sym))
        elif final in ("DİKKAT", "ÇIK", "ACİL_ÇIK", "DEĞİŞTİR"):
            if _should_send_state(sym, final):
                new_pick, lot_info = _get_last_alternative(sym)
                notifier.send_exit_signal(
                    final, sym,
                    active.get("last_score", score["total_score"]),
                    score["total_score"], final_msg, new_pick, lot_info
                )
        else:  # DEVAM
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
                            "hard_stop":  pending.get("hard_stop", 0),
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


def _check_entry_alerts(pick, lot_info, state, notifier, get_price):
    """Top picks ilk önerisi için de giriş/fırsat alımı alarmı izler."""
    try:
        sym  = pick.get("symbol","")
        ez   = pick.get("entry_zone") or {}
        elow, ehigh = ez.get("low",0), ez.get("high",0)
        if not sym or not ehigh: return
        price, _ = get_price(sym)
        if not price: return
        li = (lot_info or {}).get(sym, {})
        lots_main = li.get("lots_main") or li.get("lots", 0)
        lots_dip  = li.get("lots_dip", 0)
        dip_px    = li.get("dip_price") or round(price * 0.97, 2)
        # Giriş bölgesine girdi — günde BİR kez bildir (saatte bir tekrar etmesin;
        # zaten haberin olunca her saat 'AL' demek spam oluyordu).
        if elow and price <= ehigh and price >= elow * 0.98:
            if _should_send(sym, "GİRİŞ_BÖLGE", cooldown=86400):
                notifier._send(
                    f"🟢 {sym} GİRİŞ BÖLGESİNDE — AL",
                    f"Fiyat giriş bölgesine girdi: {_fp(price)} ₺\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"➤ ANA GİRİŞ: {lots_main:,} lot al (şimdi)\n".replace(",",".")
                    + (f"➤ FIRSAT ALIMI: {lots_dip:,} lot — {_fp(dip_px)} ₺'ye gelirse\n".replace(",",".") if lots_dip else "")
                    + f"Stop: {_fp(pick.get('stop_loss',0))} | Hedef: {_fp(pick.get('target1',0))}",
                    priority="high", tags="bell",
                    actions=notifier.action_bought(sym))
    except Exception as e:
        log.debug(f"_check_entry_alerts: {e}")


def _check_active_dip_buy(state: dict, notifier, get_price):
    """
    AKTİF pozisyonda FIRSAT ALIMI: kullanıcı %75 ile girdi; fiyat girişten
    %3 geri çekilirse kalan %25 sermaye ile "maliyet düşür" bildirimi (BİR KEZ).
    Korumalar (düşen bıçağa ekletmez):
      • Fiyat stop bölgesindeyse (stop'un %1 üstü ve altı) → GÖNDERME
      • Sinyal DİKKAT/ÇIK/ERKEN ÇIK ise (yapı bozuk) → GÖNDERME
    """
    try:
        active = state.get("active") or {}
        sym   = active.get("symbol")
        entry = active.get("entry_price", 0) or 0
        stop  = active.get("stop_loss", 0) or 0
        if not sym or not entry or active.get("dip_notified"):
            return
        price, _src = get_price(sym)
        if not price:
            return
        # UYARLAMALI TETİK: girişten stop'a YARI YOL (en az %1 çekilme).
        # Sabit %3 kullanılmaz çünkü dar stoplu pozisyonda %3 çekilme stop
        # bölgesinin içine düşer → bildirim hiç atmaz. Yarı yol her stop
        # genişliğinde geçerli bir "ucuzladı ama yapı sağlam" noktasıdır.
        _risk   = (entry - stop) if (stop and stop < entry) else entry * 0.03
        trigger = entry - max(0.5 * _risk, 0.01 * entry)
        if price > trigger:               # yeterli geri çekilme henüz yok
            return
        if stop and price <= stop * 1.01: # stop bölgesi — ekleme yapılmaz
            return
        # TAZE ZAYIFLAMA KONTROLÜ — bayat (15 dk eski) sinyale güvenme, ŞİMDİ hesapla.
        # (12.06: EK YAP bildirimi DEVAM'lık eski sinyale bakıp gönderildi, 26 dk
        # sonra ERKEN ÇIK geldi → kullanıcı tam tepede takviye yaptı. Bir daha olmasın.)
        # Taze kontrol başarısızsa GÖNDERME (şüphede para riske edilmez); 30 sn
        # sonra tekrar denenir. Ağır indirme spam'ini önlemek için 120 sn aralık.
        now = time.time()
        if now - globals().get("_dip_chk_ts", 0) < 120:
            return
        globals()["_dip_chk_ts"] = now
        try:
            import advisor
            import yfinance as yf
            import pandas as pd
            raw = yf.download([f"{sym}.IS", "XU100.IS"], period="90d",
                              auto_adjust=True, progress=False, threads=True)
            def _gdf(s):
                t = f"{s}.IS"
                try:
                    df = raw.xs(t, axis=1, level=1).dropna(how="all") \
                        if isinstance(raw.columns, pd.MultiIndex) else raw.dropna(how="all")
                    return df if len(df) >= 20 else None
                except Exception:
                    return None
            df, xu = _gdf(sym), _gdf("XU100")
            if df is None:
                log.info(f"FIRSAT ALIMI ertelendi: {sym} taze veri alınamadı.")
                return
            df.iloc[-1, df.columns.get_loc("Close")] = price   # canlı fiyatı yansıt
            c = df["Close"]
            all_returns = {
                "r5":  {sym: advisor._pct(float(c.iloc[-1]), float(c.iloc[-6]))  if len(c) > 5  else 0},
                "r20": {sym: advisor._pct(float(c.iloc[-1]), float(c.iloc[-21])) if len(c) > 20 else 0},
                "r60": {sym: advisor._pct(float(c.iloc[-1]), float(c.iloc[-61])) if len(c) > 60 else 0},
            }
            cfg = _load_cfg()
            score = advisor.score_stock(sym, df, xu, all_returns, cfg["sectors"])
            sig, _msg, _xp     = advisor.check_exit(active, score)
            lvl, wmsg, wpts    = advisor.check_early_weakness(active, df, score, xu)
            if sig in ("ÇIK", "ACİL_ÇIK", "DEĞİŞTİR", "DİKKAT") or wpts >= 3:
                log.info(f"FIRSAT ALIMI İPTAL: {sym} taze kontrol zayıf "
                         f"(sinyal={sig}, zayıflama={wpts}p {wmsg}) — ekleme önerilmedi.")
                return
        except Exception as e:
            log.info(f"FIRSAT ALIMI ertelendi: taze kontrol başarısız ({e}).")
            return
        # GÜN İÇİ İVME: son 30 dk hâlâ sert aşağıysa düşen bıçak — bekle
        _c30 = _intraday_chg(sym, 30)
        if _c30 is not None and _c30 <= -0.6:
            log.info(f"FIRSAT ALIMI ertelendi: {sym} gün içi ivme aşağı ({_c30:+.1f}%/30dk).")
            return
        cap  = state.get("capital", 0) or 0
        lots = int((cap * 0.25) // price) if cap and price else 0
        if lots <= 0:
            return
        if not _should_send(sym, "AKTIF_FIRSAT_ALIM"):
            return
        active["dip_notified"] = True   # bir kez bildir
        _save_state(state)
        qty     = active.get("qty", 0) or 0
        avg_new = (entry * qty + price * lots) / max(1, qty + lots)
        _dd = (entry - price) / entry * 100
        notifier._send(
            f"⬇ {sym} FIRSAT ALIMI — maliyet düşür",
            f"Fiyat girişten %{_dd:.1f} geri çekildi: {_fp(price)} ₺ (giriş {_fp(entry)})\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"➤ {lots} lot EKLE (kalan %25 sermaye)\n"
            f"Yeni ort. maliyet ~{_fp(avg_new)} ₺ olur\n"
            f"Stop: {_fp(stop)} | Yapı sağlam (sinyal DEVAM)",
            priority="high", tags="chart_with_downwards_trend")
        log.info(f"AKTİF FIRSAT ALIMI bildirildi: {sym} @ {_fp(price)} ({lots} lot)")
    except Exception as e:
        log.debug(f"_check_active_dip_buy: {e}")


def _check_pending_entry():
    """
    Bekleyen öneri (pending_buy) için 3 alarm:
      1) Fiyat giriş bölgesine GİRDİ → "Şimdi al!" bildirimi
      2) Fiyat %3 geri çekildi → "Fırsat alımı fırsatı!" bildirimi
      3) Fiyat giriş bölgesini KAÇTI → sıradaki öneriye geç
    """
    try:
        import notifier
        sys.path.insert(0, str(BASE))
        from price_reader import get_price

        state = _load_state()
        if state.get("active"):
            # Pozisyon açık → öneri takibi yok ama FIRSAT ALIMI izlenir
            # (girişten %3 geri çekilirse kalan %25 ile maliyet düşürme)
            _check_active_dip_buy(state, notifier, get_price)
            return
        pending = state.get("pending_buy")
        if not pending:
            # Aktif pozisyon yoksa top_picks'teki ilk hisseyi de izle
            try:
                from advisor import RESULT_PATH
                d = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
                picks = d.get("top_picks", [])
                lot_info = d.get("lot_info", {})
                # Bekleme günü → "GİRİŞ BÖLGESİNDE AL" alarmı da gönderilmez.
                if picks and not d.get("no_trade_today"):
                    _check_entry_alerts(picks[0], lot_info, state, notifier, get_price)
            except Exception:
                pass
            return

        psym = pending.get("symbol", "")
        ehigh = pending.get("entry_high", 0)
        elow  = pending.get("entry_low", 0)
        if not psym or not ehigh:
            return

        price, _src = get_price(psym)
        if not price:
            return

        # ── 1. GİRİŞ BÖLGESİNE GİRDİ → "Şimdi al!" ──────────────────────
        if elow and price <= ehigh and price >= elow * 0.98:
            if _should_send(psym, "GİRİŞ_BÖLGE"):
                from advisor import RESULT_PATH
                d = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
                li = (d.get("lot_info") or {}).get(psym, {})
                lots_main = li.get("lots_main") or li.get("lots", 0)
                lots_dip  = li.get("lots_dip", 0)
                dip_px    = li.get("dip_price", round(price * 0.97, 2))
                notifier._send(
                    f"🟢 {psym} GİRİŞ BÖLGESİNDE — AL",
                    f"Fiyat giriş bölgesine girdi: {_fp(price)} ₺\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"➤ ANA GİRİŞ: {lots_main:,} lot al (şimdi)\n".replace(",",".")
                    + (f"➤ FIRSAT ALIMI: {lots_dip:,} lot — fiyat {_fp(dip_px)} ₺'ye gelirse\n".replace(",",".") if lots_dip else "")
                    + f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Stop: {_fp(pending.get('stop_loss',0))} | Hedef: {_fp(pending.get('target1',0))}",
                    priority="high", tags="bell",
                    actions=notifier.action_bought(psym))

        # ── 2. FIRSAT ALIMI: fiyat %3 geri çekildi ───────────────────────
        dip_ref = pending.get("entry_ref_price") or ehigh
        dip_target = dip_ref * 0.97
        if price <= dip_target and not pending.get("dip_notified"):
            if _should_send(psym, "FIRSAT_ALIM"):
                from advisor import RESULT_PATH
                d = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
                li = (d.get("lot_info") or {}).get(psym, {})
                lots_dip = li.get("lots_dip", 0)
                if lots_dip > 0:
                    try:
                        st2 = _load_state()
                        if st2.get("pending_buy") and st2["pending_buy"].get("symbol") == psym:
                            st2["pending_buy"]["dip_notified"] = True
                            _save_state(st2)
                    except Exception: pass
                    notifier._send(
                        f"⬇ {psym} FIRSAT ALIMI",
                        (f"Fiyat %3 geri cekildi: {_fp(price)} TL\n"
                         f"━━━━━━━━━━━━━━━━━━━━\n"
                         f"Firsat alimi: {lots_dip} lot al\n"
                         f"Ortalama maliyet dusecek.\n"
                         f"Stop: {_fp(pending.get('stop_loss',0))} | Hedef: {_fp(pending.get('target1',0))}"),
                        priority="high", tags="chart_with_downwards_trend")

        # ── 3. KAÇTI: giriş bölgesinin %1.5 üstüne çıktıysa ──────────────
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
                "hard_stop":  new_pick.get("hard_stop", 0),
                "target1":    new_pick.get("target1", 0),
                "target2":    new_pick.get("target2", 0),
                "score":      new_pick.get("total_score", 0),
                "timeframe":  new_pick.get("timeframe", ""),
                "entry_low":  new_pick.get("entry_zone", {}).get("low", 0),
                "entry_high": new_pick.get("entry_zone", {}).get("high", 0),
            }
            _record_recommended(state, new_pick["symbol"], new_pick)
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


def _dde_watchdog_loop():
    """
    DDE SELF-HEAL: Piyasa açıkken DDE feed'i düşmüşse (PC çökmesi/reboot sonrası)
    ve MatriksIQ açıksa, BIST100 Excel'ini görünmez tekrar açar. Böylece kullanıcı
    sadece MatriksIQ'yu açar; canlı fiyat kendiliğinden geri gelir. Her 120 sn.
    Bildirim: self-heal başarısızsa 10 dk'da bir ACİL bildirim.
    """
    while True:
        try:
            if _is_market_open():
                sys.path.insert(0, str(BASE))
                import ensure_dde
                if not ensure_dde.dde_live():
                    ok, msg = ensure_dde.ensure()
                    if ok:
                        log.info(f"[DDE-watchdog] Canlı fiyat geri getirildi: {msg}")
                        # Eğer daha önce DDE hatası bildirildiyse "düzeldi" bildirimi gönder
                        if _should_send("__DDE__", "DDE_RECOVERED", cooldown=300):
                            notifier._send(
                                "✅ DDE Bağlantısı Geri Geldi",
                                f"Canlı fiyat feed'i yeniden aktif: {msg}",
                                priority="default", tags="white_check_mark")
                    else:
                        log.warning(f"[DDE-watchdog] DDE düşük, açılamadı: {msg}")
                        # Her 10 dakikada bir bildirim gönder (spam olmasın)
                        if _should_send("__DDE__", "DDE_FAIL", cooldown=600):
                            if msg == "matriks-kapali":
                                notifier._send(
                                    "⚠️ MatriksIQ Kapalı — Fiyatlar Gecikmeli",
                                    "MatriksIQ çalışmıyor. Canlı fiyat alınamıyor, Yahoo (gecikmeli) kullanılıyor.\nMatriksIQ'yu aç.",
                                    priority="high", tags="warning")
                            else:
                                notifier._send(
                                    "⚠️ DDE Bağlanamadı — Fiyatlar Gecikmeli",
                                    f"DDE self-heal başarısız ({msg}). Canlı fiyat alınamıyor.\nYahoo (gecikmeli) fallback devrede.",
                                    priority="high", tags="warning")
        except Exception as e:
            log.debug(f"[DDE-watchdog] hata: {e}")
        time.sleep(120)


def _picks_refresh_loop():
    """Pozisyon YOKKEN (kullanıcı fırsat ararken) önerileri gün içi taze tutar.
    Her 10 dk'da bir top_picks'i yeniden üretir → sayfayı her açtığında güncel.
    SPAM YOK: sadece #1 öneri DEĞİŞİNCE bildirim gönderir, yoksa sessiz günceller.
    (Pozisyon varken atlar — o durumu _slow_analysis yönetir.)"""
    REFRESH_MIN = 10
    last_top = None
    while True:
        try:
            if _is_market_open():
                state = _load_state()
                if not state.get("active"):
                    import advisor, notifier
                    res  = advisor.run_analysis(refresh_only=True, quiet=True)
                    tp   = (res or {}).get("top_picks", [])
                    top1 = tp[0]["symbol"] if tp else None
                    _notrade = bool((res or {}).get("no_trade_today"))
                    if top1 and top1 != last_top and not _notrade:
                        try:
                            notifier.send_daily_pick(tp[0], (res.get("lot_info") or {}).get(top1))
                        except Exception:
                            pass
                        last_top = top1
                        log.info(f"[Öneri-tazele] Yeni #1 öneri: {top1}")
                    elif top1 and _notrade:
                        # Bekleme günü: aday var ama kalite eşiği altında → "AL"
                        # bildirimi GÖNDERME (kart 'izleme' olarak gösterir).
                        log.info(f"[Öneri-tazele] {top1} aday ama bekleme günü — bildirim yok")
                    elif top1:
                        log.info(f"[Öneri-tazele] #1 aynı ({top1}) — sessiz güncellendi")
                    # pending_buy'ı KARTLA SENKRON tut: kart top1 gösterirken
                    # pending eski sembolde kalmasın (giriş/kaçtı alarmları
                    # yanlış hisseyi izler, Aldım'da seviye karışır).
                    if top1:
                        st2 = _load_state()
                        pb  = st2.get("pending_buy")
                        if not st2.get("active") and pb and pb.get("symbol") != top1:
                            p0 = tp[0]
                            st2["pending_buy"] = {
                                "symbol":     top1,
                                "stop_loss":  p0.get("stop_loss", 0),
                                "hard_stop":  p0.get("hard_stop", 0),
                                "target1":    p0.get("target1", 0),
                                "target2":    p0.get("target2", 0),
                                "score":      p0.get("total_score", 0),
                                "timeframe":  p0.get("timeframe", ""),
                                "entry_low":  (p0.get("entry_zone") or {}).get("low", 0),
                                "entry_high": (p0.get("entry_zone") or {}).get("high", 0),
                            }
                            _record_recommended(st2, top1, p0)
                            _save_state(st2)
                            log.info(f"[Öneri-tazele] pending_buy kartla senkronlandı: "
                                     f"{pb.get('symbol')} → {top1}")
                else:
                    last_top = None   # pozisyon açıldı; bir sonraki flat dönemde yeniden bildir
        except Exception as e:
            log.debug(f"[Öneri-tazele] hata: {e}")
        time.sleep(REFRESH_MIN * 60)


def main():
    log.info("Monitor başlatıldı. Hızlı:5sn | Yavaş:15dk | Öneri-tazele:10dk")
    print("[Monitor] Başlatıldı — Hızlı:5sn | Yavaş:15dk | Log:", log_path)

    # DDE self-heal watchdog (canlı fiyat feed'i düşerse otomatik geri getirir)
    threading.Thread(target=_dde_watchdog_loop, daemon=True).start()

    # Kullanıcı komut dinleyici (HTML "Sattım"/"Aldım" butonları — 7/24, 4 sn)
    threading.Thread(target=_user_action_loop, daemon=True).start()

    # Gün-içi öneri tazeleyici (pozisyon yokken her 10 dk top_picks güncellenir)
    threading.Thread(target=_picks_refresh_loop, daemon=True).start()

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
