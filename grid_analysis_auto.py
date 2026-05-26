#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GridTracker - Otomatik Grid Analizi (v5 - Mimari Yeniden Tasarim)
==================================================================
Temel felsefe:
  Grid bot YONSEL pozisyon degil, OSILASYON uzerine kar eder.
  Fiyat destek-direnc arasinda gidip geldiginde her tur = kar.
  Downtrend'de alim emirleri birikir, sermaye mahsur kalir = zarar.

v5 Kritik Duzeltmeler:
  * Destek/Direnc artik 60-gun %15/%85 PERCENTILE — min/max degil.
    Bu sayede range metrikleri artik ANLAMLI (eskiden hep %100 cikiyordu).
  * Range Quality -> Osisilasyon Kalitesi (midpoint crossing sayisi).
    Gerçek salınım olcumu: fiyat range ortasini kac kez gecti?
  * Range Stability -> Range Hold Orani (anlamli, artik trivial degil).
  * Trend: MA20 egimi + 20-gun momentum kombinasyonu.
    Ideal: Hafif yukselis (grid hem alim hem satim doldurur).
    Kotu: Guclu downtrend (alimlar birikir, zarar).

Grid Skoru bilesenleri:
  Osisilasyon Kalitesi  0-3.0   Midpoint crossing — gercek osilasyon
  Range Hold Orani      0-2.0   Percentile range'de kac gun kaldi
  Volatilite Uyumu      0-2.5   ATR/fiyat %2-5 tatli nokta
  Trend Guvenligi      -2.0/+1.5  MA20 egimi + momentum
  Trigger Hizi          0-1.5   ATR/grid_interval → gunluk dolum
  Likidite              0-1.5   Gunluk hacim TL
  Giris Zamanlama       0-1.0   RSI + fiyat pozisyonu bonusu
  Range Kirilma Cezasi -2.0     Son 5 gunde kirildiysa (Hold icinde)

  RAW_MIN = -4.0  (hold kirma + downtrend cezasi)
  RAW_MAX = 13.0  (tum bilesenler max)
  Grid Skoru -> [0, 10]

  Final = (0.85 * grid_score + 0.15 * profit_norm) * market_multiplier

Kullanim:
  python grid_analysis_auto.py          # Normal calistir
  python grid_analysis_auto.py --test   # Sadece logla, kaydetme
  python grid_analysis_auto.py --force  # Tatil/hafta sonu da calistir
"""

import sys, json, logging, subprocess, argparse, urllib.request
from pathlib import Path
from datetime import date, datetime

for _pkg in ['yfinance', 'pandas', 'numpy', 'holidays']:
    try:
        __import__(_pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg, '-q'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

import yfinance as yf
import pandas as pd
import numpy as np
import holidays as _holidays

SCRIPT_DIR    = Path(__file__).parent
LOG_FILE      = SCRIPT_DIR / 'grid_analysis.log'
CONFIG_FILE   = SCRIPT_DIR / 'grid_analysis_config.json'
RESULT_FILE   = SCRIPT_DIR / 'grid_analysis_result.json'
FIREBASE_BASE = 'https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app/gridtracker'
SCORE_HIST_MAX = 10  # Her hisse için saklanacak maksimum gün


# =============================================================================
#  FİREBASE YARDIMCILARI
# =============================================================================

def fb_get(path):
    """Firebase'den JSON oku."""
    try:
        url = f'{FIREBASE_BASE}/{path}.json'
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        log.debug(f'Firebase GET {path}: {e}')
        return None

def fb_put(path, data):
    """Firebase'e JSON yaz."""
    try:
        url = f'{FIREBASE_BASE}/{path}.json'
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(url, data=payload, method='PUT')
        req.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(req, timeout=10):
            pass
        return True
    except Exception as e:
        log.warning(f'Firebase PUT {path}: {e}')
        return False


def _notify_verdict(cfg, active_r, best_r, active_sym):
    """Karar hesapla, önceki kararla karşılaştır, değiştiyse ntfy gönder."""
    gs   = active_r.get('grid_score', 0) if active_r else 0
    fs   = active_r.get('final_score', 0) if active_r else 0
    best_sym = (best_r.get('symbol', '') if best_r else '').replace('.IS', '')
    best_fs  = best_r.get('final_score', 0) if best_r else 0
    score_diff = (best_fs - fs) if (best_r and best_sym != active_sym) else 0

    # Karar
    if gs < 3.5:
        verdict, emoji = 'cik', '🚨'
        reason = f'Grid skoru çok düşük ({gs:.1f}/10)'
    elif gs < 4 or score_diff > 2.5:
        verdict, emoji = 'dikkat', '⚠️'
        reason = (f'Skor düşük ({gs:.1f}/10)' if gs < 4
                  else f'{best_sym} {score_diff:.1f} puan daha iyi')
    else:
        verdict, emoji = 'devam', '✅'
        reason = f'Skor iyi ({gs:.1f}/10)'

    log.info(f'[Pozisyon] {active_sym}: {verdict.upper()} — {reason}')

    # Önceki kararı Firebase'den oku
    prev_verdict = fb_get('settings/pmVerdict') or ''
    fb_put('settings/pmVerdict', verdict)

    # Sadece kötüleşme varsa bildir: devam→dikkat, devam→cik, dikkat→cik
    should_notify = False
    if verdict == 'cik':
        should_notify = True
    elif verdict == 'dikkat' and prev_verdict == 'devam':
        should_notify = True

    if should_notify:
        title_map = {'cik': f'{emoji} {active_sym} — ÇIK',
                     'dikkat': f'{emoji} {active_sym} — DİKKAT'}
        body_parts = [reason]
        if best_r and best_sym != active_sym and score_diff > 0:
            body_parts.append(f'Yeni öneri: {best_sym} ({score_diff:.1f} puan fark)')
        prio = 'urgent' if verdict == 'cik' else 'high'
        tags = 'rotating_light' if verdict == 'cik' else 'warning'
        send_ntfy(cfg, title_map[verdict], '\n'.join(body_parts), prio, tags)
    else:
        log.info(f'[ntfy] Bildirim gerekmiyor ({prev_verdict} → {verdict})')


def send_ntfy(cfg, title, body, priority='default', tags='chart_with_downwards_trend'):
    """ntfy.sh üzerinden push bildirimi gönder."""
    topic = (cfg.get('ntfy_topic') or '').strip()
    if not topic:
        return  # topic ayarlanmamış, sessizce geç
    try:
        url = f'https://ntfy.sh/{topic}'.encode('utf-8')
        req = urllib.request.Request(f'https://ntfy.sh/{topic}',
                                     data=body.encode('utf-8'), method='POST')
        req.add_header('Title',    title)
        req.add_header('Priority', priority)
        req.add_header('Tags',     tags)
        req.add_header('Content-Type', 'text/plain; charset=utf-8')
        with urllib.request.urlopen(req, timeout=10):
            pass
        log.info(f'[ntfy] Bildirim gonderildi: {title}')
    except Exception as e:
        log.warning(f'[ntfy] Hata: {e}')

_handlers = [logging.FileHandler(LOG_FILE, encoding='utf-8')]
if sys.stdout:
    _handlers.append(logging.StreamHandler(sys.stdout))
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s',
                    handlers=_handlers)
log = logging.getLogger('GridAnaliz')

BIST50 = [
    'AKBNK.IS', 'AKSEN.IS', 'ALARK.IS', 'ARCLK.IS', 'ASELS.IS',
    'BIMAS.IS', 'CCOLA.IS', 'CIMSA.IS', 'DOHOL.IS', 'EKGYO.IS',
    'ENJSA.IS', 'ENKAI.IS', 'EREGL.IS', 'FROTO.IS', 'GARAN.IS',
    'GUBRF.IS', 'HALKB.IS', 'HEKTS.IS', 'ISCTR.IS', 'KCHOL.IS',
    'TRALT.IS', 'KRDMD.IS', 'MGROS.IS', 'ODAS.IS',  'OTKAR.IS',
    'OYAKC.IS', 'PETKM.IS', 'PGSUS.IS', 'SAHOL.IS', 'SASA.IS',
    'SISE.IS',  'SKBNK.IS', 'SOKM.IS',  'TAVHL.IS', 'TCELL.IS',
    'THYAO.IS', 'TKFEN.IS', 'TOASO.IS', 'TTKOM.IS', 'TTRAK.IS',
    'TUPRS.IS', 'ULKER.IS', 'VAKBN.IS', 'VESTL.IS', 'YKBNK.IS',
    'ZOREN.IS', 'LOGO.IS',  'KORDS.IS', 'BRSAN.IS', 'DOAS.IS',
]

MIN_GRID_SCORE = 3.5   # 10 uzerinden minimum kabul skoru


# =============================================================================
#  CONFIG & TICK
# =============================================================================

def load_config():
    defaults = {'capital': 1400000, 'commission_rate': 0.0001,
                'safety_buffer': 0.90, 'atr_period': 14, 'grid_atr_ratio': 0.15}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            defaults.update(cfg)
        except Exception as e:
            log.warning(f'Config okunamadi: {e}')
    return defaults

def get_tick_size(price):
    if price < 20:   return 0.01
    if price < 50:   return 0.02
    if price < 100:  return 0.05
    if price < 250:  return 0.10
    if price < 500:  return 0.25
    if price < 1000: return 0.50
    if price < 2500: return 1.00
    return 2.50

def round_to_tick(value, tick):
    return round(round(value / tick) * tick, 6)


# =============================================================================
#  TEMEL HESAPLAMALAR
# =============================================================================

def calc_atr(high, low, close, period=14):
    tr = pd.concat([high - low,
                    (high - close.shift(1)).abs(),
                    (low  - close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_rsi(close, period=14):
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=period-1, min_periods=period).mean()
    loss  = (-delta).clip(lower=0).ewm(com=period-1, min_periods=period).mean()
    return 100 - (100 / (1 + gain / loss.replace(0, np.nan)))


# =============================================================================
#  DESTEK / DIRENC — Percentile tabanlı (v5 kritik degisiklik)
# =============================================================================

def calc_support_resistance(close, lookback=60):
    """
    v5: Support/resistance artik min/max DEGIL, 60-gun percentile.
    support  = %15 percentile  (fiyatin %15'i bu seviyenin altinda)
    resistance = %85 percentile  (fiyatin %15'i bu seviyenin ustunde)

    Neden onemli?
    Min/max kullanildiginda range stabilitesi her zaman %100 cikar (trivial).
    Percentile kullanildiginda range metrikleri gercek ve anlamli olur.
    """
    n = min(lookback, len(close) - 1)
    recent = close.iloc[-n:]
    support    = float(np.percentile(recent, 15))
    resistance = float(np.percentile(recent, 85))
    return support, resistance


# =============================================================================
#  1. OSISILASYON KALİTESİ — Midpoint Crossing (v5 yeni)
# =============================================================================

def calc_oscillation_quality(close, support, resistance):
    """
    Grid bot icin EN KRITIK OLCUM: fiyat range'in tam ortasini kac kez gecti?
    Her gecis = bir tam salınim = bir potansiyel grid tur kari.

    Neden midpoint crossing?
    - Eski sistem destek/direnc "dokunma" sayiyordu → cok toleransli, anlamsiz
    - Midpoint crossing GERCEK OSISILASYONU olcer
    - Fiyat ortayi gecmeden ne destek ne direnc anlamli bir rol oynar
    """
    if resistance <= support:
        return 0.0, 'Osc=range-gecersiz'

    lookback  = min(30, len(close))
    recent    = close.iloc[-lookback:]
    midpoint  = (support + resistance) / 2

    crossings = 0
    prev_above = None
    for p in recent:
        above = float(p) > midpoint
        if prev_above is not None and above != prev_above:
            crossings += 1
        prev_above = above

    if crossings >= 10:
        score, tag = 3.0, f'Osc={crossings}x(cok-aktif!)'
    elif crossings >= 7:
        score, tag = 2.5, f'Osc={crossings}x(aktif)'
    elif crossings >= 5:
        score, tag = 2.0, f'Osc={crossings}x(iyi)'
    elif crossings >= 3:
        score, tag = 1.0, f'Osc={crossings}x(orta)'
    elif crossings >= 1:
        score, tag = 0.5, f'Osc={crossings}x(az)'
    else:
        score, tag = 0.0, f'Osc={crossings}x(yok!-kotu)'

    return round(score, 2), tag


# =============================================================================
#  2. RANGE HOLD ORANI — Percentile range ile anlamli (v5 kritik duzeltme)
# =============================================================================

def calc_range_hold(close, low, high, support, resistance):
    """
    Son 30 gunde fiyat percentile-tabanli support-resistance arasinda kac gun kaldi?

    v4'teki Range Stability her zaman %100 veriyordu cunku
    support=30-gun-min, resistance=30-gun-max diye tanimliyordu.
    Percentile kullaniliginda bu olcum GERCEKTEN ANLAMLI.

    Ayrica son 5 gunde ciddi kirma varsa ceza uygulanir.
    """
    if resistance <= support:
        return 0.0, 'Hold=range-gecersiz'

    lookback   = min(30, len(close))
    recent_c   = close.iloc[-lookback:]
    recent_l   = low.iloc[-lookback:]
    recent_h   = high.iloc[-lookback:]

    # %5 buffer ile range icinde mi?
    buf = (resistance - support) * 0.05
    in_range = ((recent_c >= support - buf) & (recent_c <= resistance + buf)).sum()
    hold_pct  = in_range / lookback

    if hold_pct >= 0.85:
        base_score, base_sig = 2.0, f'Hold={hold_pct*100:.0f}%(guclu)'
    elif hold_pct >= 0.72:
        base_score, base_sig = 1.5, f'Hold={hold_pct*100:.0f}%(iyi)'
    elif hold_pct >= 0.58:
        base_score, base_sig = 0.75, f'Hold={hold_pct*100:.0f}%(orta)'
    else:
        base_score, base_sig = 0.0, f'Hold={hold_pct*100:.0f}%(zayif)'

    # Son 5 gunde ciddi kirma cezasi
    last5_low  = float(recent_l.iloc[-5:].min())
    last5_high = float(recent_h.iloc[-5:].max())
    penalty, pen_sig = 0.0, ''

    if last5_low < support * 0.96:
        penalty, pen_sig = -2.0, ' CEZA=destek-kirdi(!)'
    elif last5_high > resistance * 1.04:
        penalty, pen_sig = -0.5, ' CEZA=direnc-asti'

    return round(base_score + penalty, 2), base_sig + pen_sig


# =============================================================================
#  3. VOLATİLİTE UYUMU — ATR/fiyat tatlı noktası
# =============================================================================

def calc_volatility_score(atr, price):
    """
    Grid bot icin ideal volatilite: ATR/fiyat %2-5.
    Cok az  → az islem → az kar.
    Cok fazla → range kirilir → zarar riski.
    """
    if price <= 0:
        return 0.0, 'Vol=sifir-fiyat'
    ratio = atr / price * 100

    if 2.5 <= ratio <= 4.0:
        return 2.5, f'Vol={ratio:.1f}%(ideal)'
    elif 2.0 <= ratio < 2.5 or 4.0 < ratio <= 5.0:
        return 2.0, f'Vol={ratio:.1f}%(iyi)'
    elif 1.5 <= ratio < 2.0 or 5.0 < ratio <= 6.0:
        return 1.0, f'Vol={ratio:.1f}%(kabul)'
    elif 1.0 <= ratio < 1.5:
        return 0.5, f'Vol={ratio:.1f}%(dusuk)'
    else:
        return 0.0, f'Vol={ratio:.1f}%(uygunsuz)'


# =============================================================================
#  4. TREND GÜVENLİĞİ — MA20 eğimi + momentum (v5 rafine)
# =============================================================================

def calc_trend_score(close):
    """
    Grid bot icin trend yonu kritik.

    IDEAL:  Hafif yukselis veya yatay.
            Grid hem alim hem satim doldurur = maksimum kar.
    KOTU:   Guclu downtrend.
            Alim emirleri birikir, fiyat asagida mahsur = buyuk zarar.
    DIKKAT: Cok hizli yukselis de tehlikelidir.
            Direnc kirip kacabilir, satim emirleri bos kalir.

    MA20 egimi (10-gunluk), MA50 pozisyonu ve 20-gun momentum birlikte degerlendirilir.
    """
    if len(close) < 52:
        return 0.0, 'Trend=veri-yetersiz'

    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()

    price     = float(close.iloc[-1])
    ma20_now  = float(ma20.iloc[-1])
    ma50_now  = float(ma50.iloc[-1])
    ma20_10d  = float(ma20.iloc[-11])

    # MA20 10-gunluk egim (yuzde)
    ma20_slope = (ma20_now - ma20_10d) / ma20_10d * 100 if ma20_10d > 0 else 0.0

    # 20-gunluk fiyat momentum
    p20 = float(close.iloc[-21]) if len(close) >= 21 else float(close.iloc[0])
    mom20 = (price - p20) / p20 * 100 if p20 > 0 else 0.0

    above_ma50 = price > ma50_now
    above_ma20 = price > ma20_now

    # Ideal: MA50 ustunde, MA20 hafif yukseliyor, momentum +0 ile +8%
    if above_ma50 and above_ma20 and 0.3 <= ma20_slope <= 2.5 and 0 <= mom20 <= 10:
        return 1.5, f'Trend=IDEAL(egim={ma20_slope:.1f}%,mom={mom20:.1f}%)'

    # Iyi: MA50 ustunde, MA20 ustunde ama cok hizli yukseliyor
    if above_ma50 and above_ma20 and ma20_slope > 2.5:
        return 1.0, f'Trend=hizli-yukselis(egim={ma20_slope:.1f}%,mom={mom20:.1f}%)'

    # Iyi: MA50 ustunde, MA20 yatay/hafif asagi
    if above_ma50 and above_ma20:
        return 1.0, f'Trend=yukari-yatay(egim={ma20_slope:.1f}%,mom={mom20:.1f}%)'

    # Kabul: MA50 ustunde, MA20 altinda (gecikmeli duzeltme)
    if above_ma50 and not above_ma20:
        return 0.5, f'Trend=notr(MA50-ustunde,mom={mom20:.1f}%)'

    # Hafif risk: MA50 altinda ama MA20 yukseliyor (toparlanma)
    if not above_ma50 and ma20_slope > 1.0 and mom20 > 0:
        return 0.0, f'Trend=toparlanma-denemesi(egim={ma20_slope:.1f}%)'

    # Orta risk: MA50 altinda, hafif asagi trend
    if not above_ma50 and mom20 >= -5:
        return -0.5, f'Trend=hafif-asagi(mom={mom20:.1f}%)'

    # Yuksek risk: MA50 altinda, ciddi asagi trend
    if not above_ma50 and mom20 < -5 and ma20_slope > -1.5:
        return -1.0, f'Trend=asagi(mom={mom20:.1f}%)'

    # CEZA: Guclu downtrend — alimlar birikir, zarar riski yuksek
    return -2.0, f'Trend=ASAGI-CEZA(egim={ma20_slope:.1f}%,mom={mom20:.1f}%)'


# =============================================================================
#  5. TRIGGER HIZI — Günde kaç grid dolumu?
# =============================================================================

def calc_trigger_score(atr, grid_interval):
    """
    ATR / grid_interval = tahmini gunluk tetiklenme sayisi.
    Ne kadar cok tetiklenirse o kadar cok kar.
    """
    if grid_interval <= 0:
        return 0.0, 'Tetik=gecersiz'
    triggers = atr / grid_interval

    if triggers >= 10:
        return 1.5, f'Tetik={triggers:.1f}/gun(cok-aktif!)'
    elif triggers >= 7:
        return 1.2, f'Tetik={triggers:.1f}/gun(aktif)'
    elif triggers >= 5:
        return 0.8, f'Tetik={triggers:.1f}/gun(iyi)'
    elif triggers >= 3:
        return 0.4, f'Tetik={triggers:.1f}/gun(orta)'
    else:
        return 0.0, f'Tetik={triggers:.1f}/gun(az)'


# =============================================================================
#  6. LİKİDİTE — Günlük işlem hacmi
# =============================================================================

def calc_liquidity_score(volume, price):
    """Ortalama gunluk islem hacmi TL cinsinden."""
    if len(volume) < 5:
        return 0.0, 'Hacim=veri-yok'
    avg_vol_tl = float(volume.iloc[-10:].mean()) * price / 1_000_000  # milyon TL

    if avg_vol_tl >= 500:
        return 1.5, f'Hacim={avg_vol_tl:.0f}M(cok-likit!)'
    elif avg_vol_tl >= 100:
        return 1.0, f'Hacim={avg_vol_tl:.0f}M(likit)'
    elif avg_vol_tl >= 30:
        return 0.5, f'Hacim={avg_vol_tl:.0f}M(orta)'
    else:
        return 0.0, f'Hacim={avg_vol_tl:.0f}M(dusuk)'


# =============================================================================
#  7. GİRİŞ ZAMANLAMA BONUSU — RSI + pozisyon
# =============================================================================

def calc_entry_timing_bonus(close, support, resistance):
    """
    Simdi grid acmak icin iyi zaman mi?
    RSI 40-55 + range alt-orta bolge = optimal entry.
    """
    rsi_s  = calc_rsi(close, 14)
    rsi    = float(rsi_s.iloc[-1]) if not rsi_s.dropna().empty else 50.0
    price  = float(close.iloc[-1])
    rng    = resistance - support
    pct    = (price - support) / rng if rng > 0 else 0.5

    bonus = 0.0
    sigs  = []

    # RSI bonusu
    if 40 <= rsi <= 55:
        bonus += 0.5
        sigs.append(f'RSI={rsi:.0f}(ideal)')
    elif 35 <= rsi < 40 or 55 < rsi <= 62:
        bonus += 0.25
        sigs.append(f'RSI={rsi:.0f}(kabul)')
    elif rsi < 35:
        bonus += 0.1
        sigs.append(f'RSI={rsi:.0f}(asiri-satim)')
    # RSI > 62 → bonus yok (asiri alim, dikkatli)

    # Fiyat pozisyonu bonusu
    if 0.25 <= pct <= 0.60:
        bonus += 0.5
        sigs.append(f'Pos={pct*100:.0f}%(orta-ideal)')
    elif 0.10 <= pct < 0.25:
        bonus += 0.35
        sigs.append(f'Pos={pct*100:.0f}%(destek-yakin)')
    elif 0.0 <= pct < 0.10:
        bonus += 0.2
        sigs.append(f'Pos={pct*100:.0f}%(destek-dibinde)')
    elif pct < 0.0:
        # Fiyat percentile range altinda: downtrend kirma — bonus yok
        sigs.append(f'Pos={pct*100:.0f}%(RANGE-ALTI-dikkat)')
    # pct > 0.60 → bonus yok (direnc yakini)

    return round(min(bonus, 1.0), 2), ', '.join(sigs)


# =============================================================================
#  ANA GRID SKORU — v5
# =============================================================================

def calc_grid_score(high_s, low_s, close_s, volume,
                    support, resistance, atr, grid_interval):
    """
    v5 Grid Bot Skoru — 7 bilesenden olusan kapsamli sistem.

    Normalize: RAW_MIN=-4.0, RAW_MAX=13.0 → [0, 10]
    """
    raw     = 0.0
    signals = []

    price = float(close_s.iloc[-1])

    # 1. Osisilasyon kalitesi (midpoint crossing)
    s, sig = calc_oscillation_quality(close_s, support, resistance)
    raw += s; signals.append(sig)

    # 2. Range hold orani (percentile range — artik anlamli)
    s, sig = calc_range_hold(close_s, low_s, high_s, support, resistance)
    raw += s; signals.append(sig)

    # 3. Volatilite uyumu
    s, sig = calc_volatility_score(atr, price)
    raw += s; signals.append(sig)

    # 4. Trend guvenligi (downtrend cezali)
    s, sig = calc_trend_score(close_s)
    raw += s; signals.append(sig)

    # 5. Trigger hizi
    s, sig = calc_trigger_score(atr, grid_interval)
    raw += s; signals.append(sig)

    # 6. Likidite
    s, sig = calc_liquidity_score(volume, price)
    raw += s; signals.append(sig)

    # 7. Giris zamanlama bonusu
    s, sig = calc_entry_timing_bonus(close_s, support, resistance)
    raw += s; signals.append(sig)

    # Normalize: [-4.0, 13.0] → [0, 10]
    # RAW_MIN: range-kirma(-2.0) + downtrend-ceza(-2.0) = -4.0
    # RAW_MAX: osc(3.0)+hold(2.0)+vol(2.5)+trend(1.5)+tetik(1.5)+hacim(1.5)+timing(1.0) = 13.0
    RAW_MIN = -4.0
    RAW_MAX = 13.0
    normalized = (raw - RAW_MIN) / (RAW_MAX - RAW_MIN) * 10.0
    final = round(max(0.0, min(normalized, 10.0)), 2)

    return final, ', '.join(s for s in signals if s)


# =============================================================================
#  BIST100 PİYASA BAĞLAMI
# =============================================================================

def get_market_context():
    """
    BIST100 trend durumu → skor carpani.
    Piyasa dususundeyse tum hisselerde risk artar.
    """
    try:
        xu = yf.Ticker('XU100.IS').history(period='40d', interval='1d', auto_adjust=True)
        if xu is None or len(xu) < 10:
            return 1.0, 'Piyasa=bilinmiyor'
        c    = xu['Close']
        ma20 = c.rolling(min(20, len(c))).mean()
        price = float(c.iloc[-1])
        ma_v  = float(ma20.iloc[-1])
        mom5  = (float(c.iloc[-1]) - float(c.iloc[-6])) / float(c.iloc[-6]) * 100 \
                if len(c) >= 6 else 0.0
        if price > ma_v and mom5 > 1.5:
            return 1.10, 'Piyasa=yukselis(+)'
        elif price > ma_v:
            return 1.05, 'Piyasa=yukari-trend'
        elif price < ma_v and mom5 < -2.0:
            return 0.85, 'Piyasa=DUSUS(!)'
        else:
            return 1.0,  'Piyasa=notr'
    except Exception:
        return 1.0, 'Piyasa=bilinmiyor'


# =============================================================================
#  HİSSE ANALİZİ
# =============================================================================

def analyze_stock(ticker, cfg, min_score=None):
    """
    min_score=None -> MIN_GRID_SCORE kullan (varsayilan BIST50 taramasi).
    min_score=0    -> skor filtresi yok (aktif hisse analizi icin).
    """
    if min_score is None:
        min_score = MIN_GRID_SCORE
    try:
        df = yf.Ticker(ticker).history(period='90d', interval='1d', auto_adjust=True)
        if df is None or len(df) < 55:   # MA50 + buffer icin
            return None

        close  = df['Close']
        high   = df['High']
        low    = df['Low']
        volume = df['Volume']

        price = float(close.iloc[-1])
        if price <= 5.0:
            return None

        # ATR
        atr_s = calc_atr(high, low, close, cfg['atr_period'])
        atr   = float(atr_s.iloc[-1])
        if pd.isna(atr) or atr <= 0:
            return None

        # Volatilite filtresi — cok yuksek = grid calismaz (aktif hisse icin atla)
        if min_score > 0 and atr / price > 0.08:
            return None

        # v5: Percentile tabanli destek / direnc (60-gun, %15/%85)
        support, resistance = calc_support_resistance(close, lookback=60)
        if resistance <= support or resistance <= price * 0.98:
            return None

        # Grid araligi
        tick          = get_tick_size(price)
        grid_interval = max(tick, round_to_tick(atr * cfg['grid_atr_ratio'], tick))
        if grid_interval <= 0:
            return None

        # Grid sayilari (percentile range icerisinde)
        sell_grids  = max(1, int((resistance - price) / grid_interval))
        buy_grids   = max(1, int((price - support)    / grid_interval))
        total_grids = sell_grids + buy_grids
        if total_grids < 4:
            return None

        # Sermaye hesabi
        eff_cap         = cfg['capital'] * cfg['safety_buffer']
        avg_buy_price   = price - (buy_grids  / 2.0) * grid_interval
        avg_sell_price  = price + (sell_grids / 2.0) * grid_interval
        capital_per_lot = (buy_grids * avg_buy_price) + (sell_grids * price)
        if capital_per_lot <= 0:
            return None
        lots = int(eff_cap / capital_per_lot)
        if lots < 1:
            return None

        # Beklenen gunluk kar
        daily_triggers  = atr / grid_interval
        profit_per_trig = lots * grid_interval
        comm_per_trig   = lots * cfg['commission_rate'] * (avg_buy_price + avg_sell_price)
        daily_profit    = daily_triggers * (profit_per_trig - comm_per_trig)
        if daily_profit <= 0:
            return None

        # Grid skoru (v5)
        grid_score, signals = calc_grid_score(
            high, low, close, volume,
            support, resistance, atr, grid_interval
        )
        if grid_score < min_score:
            return None

        pct_up   = (resistance - price) / price * 100
        pct_down = (price - support)    / price * 100

        # RSI (bilgi icin)
        rsi_s = calc_rsi(close, 14)
        rsi   = float(rsi_s.iloc[-1]) if not rsi_s.dropna().empty else 0.0

        return {
            'symbol':        ticker.replace('.IS', ''),
            'price':         round(price,         2),
            'atr':           round(atr,           2),
            'support':       round(support,       2),
            'resistance':    round(resistance,    2),
            'grid_interval': round(grid_interval, 2),
            'lots':          lots,
            'buy_grids':     buy_grids,
            'sell_grids':    sell_grids,
            'total_grids':   total_grids,
            'pct_up':        round(pct_up,        2),
            'pct_down':      round(pct_down,      2),
            'daily_profit':  round(daily_profit,  0),
            'capital_used':  round(capital_per_lot * lots, 0),
            'grid_score':    grid_score,
            'rsi':           round(rsi, 1),
            'signals':       signals,
            '_raw_profit':   daily_profit,
        }
    except Exception as e:
        log.debug(f'{ticker}: {e}')
        return None


# =============================================================================
#  FINAL SKOR
# =============================================================================

def calc_final_scores(results, market_mult):
    """
    Final = (0.85 * grid_score + 0.15 * profit_norm) * market_mult
    profit_norm: en dusuk karla en yuksek kar arasinda 0-10 normalize.
    """
    if not results:
        return results
    profits = [r['_raw_profit'] for r in results]
    min_p, max_p = min(profits), max(profits)
    rng_p = max_p - min_p if max_p > min_p else 1.0
    for r in results:
        profit_norm      = (r['_raw_profit'] - min_p) / rng_p * 10.0
        base             = 0.85 * r['grid_score'] + 0.15 * profit_norm
        r['final_score'] = round(base * market_mult, 3)
        del r['_raw_profit']
    return results


# =============================================================================
#  YARDIMCI
# =============================================================================

def is_working_day():
    today = date.today()
    if today.weekday() >= 5:
        return False
    return today not in _holidays.Turkey(years=today.year)


# =============================================================================
#  ANA FONKSİYON
# =============================================================================

def run(dry_run=False, force=False):
    log.info('==========================================')
    log.info('  GRID ANALIZi v5 - Mimari Yeniden Tasarim')
    log.info('==========================================')

    if not force and not is_working_day():
        log.info('Bugun tatil/hafta sonu. (--force ile zorla)')
        return

    cfg = load_config()
    log.info(f'Sermaye    : {cfg["capital"]:,.0f} TL')
    log.info(f'Min.Grid P.: {MIN_GRID_SCORE}/10')

    log.info('Piyasa kontrol ediliyor...')
    market_mult, market_sig = get_market_context()
    log.info(f'Piyasa     : {market_sig}  (carpan={market_mult:.2f})')
    log.info(f'Taranacak  : {len(BIST50)} hisse')
    log.info('')

    results = []
    for i, ticker in enumerate(BIST50):
        r = analyze_stock(ticker, cfg)
        if r:
            results.append(r)
            log.info(
                f'[{i+1:2d}/{len(BIST50)}] {r["symbol"]:8s} '
                f'fiyat={r["price"]:7.2f}  '
                f'RSI={r["rsi"]:5.1f}  '
                f'GridP={r["grid_score"]:4.1f}  '
                f'kar={r["daily_profit"]:6,.0f} TL'
                f'  | {r["signals"]}'
            )
        else:
            log.debug(f'[{i+1:2d}/{len(BIST50)}] {ticker}: atlandi')

    log.info('')
    log.info(f'Sonuc: {len(results)} gecerli / {len(BIST50)-len(results)} atlandi')

    if not results:
        log.error('Hicbir hisse grid esigini gecemedi!')
        return

    results = calc_final_scores(results, market_mult)
    results.sort(key=lambda x: x['final_score'], reverse=True)

    log.info('')
    log.info('----------------------------------------')
    log.info(f'  TOP 5  [{market_sig} / carpan={market_mult:.2f}]')
    log.info('----------------------------------------')
    for idx, r in enumerate(results[:5]):
        marker = '* EN IYI' if idx == 0 else f'  #{idx+1}     '
        log.info(f'{marker} : {r["symbol"]:8s}  GridP={r["grid_score"]:4.1f}  '
                 f'Final={r["final_score"]:5.3f}  RSI={r["rsi"]:5.1f}  '
                 f'kar={r["daily_profit"]:,.0f} TL')
        log.info(f'           {r["signals"]}')
    log.info('----------------------------------------')

    best = results[0]
    log.info('')
    log.info(f'SECILEN      : {best["symbol"]}')
    log.info(f'  Fiyat      : {best["price"]:.2f} TL')
    log.info(f'  ATR(14)    : {best["atr"]:.2f} TL  (Vol={best["atr"]/best["price"]*100:.1f}%)')
    log.info(f'  RSI(14)    : {best["rsi"]:.1f}')
    log.info(f'  Grid Puan  : {best["grid_score"]}/10')
    log.info(f'  Final Puan : {best["final_score"]}/10')
    log.info(f'  Sinyaller  : {best["signals"]}')
    log.info(f'  Destek     : {best["support"]:.2f} TL  (%{best["pct_down"]:.1f} asagi)')
    log.info(f'  Direnc     : {best["resistance"]:.2f} TL  (%{best["pct_up"]:.1f} yukari)')
    log.info(f'  Grid Aral. : {best["grid_interval"]:.2f} TL')
    log.info(f'  Lot Sayisi : {best["lots"]}')
    log.info(f'  Grid Sayisi: {best["total_grids"]}  ({best["buy_grids"]} al + {best["sell_grids"]} sat)')
    log.info(f'  Bkl.Gun.Kar: ~{best["daily_profit"]:,.0f} TL')
    log.info(f'  Kull.Serm. : {best["capital_used"]:,.0f} TL')
    log.info('----------------------------------------')

    if dry_run:
        log.info('[TEST] Kaydetme atlandi.')
        return

    best['updated_at']    = datetime.now().strftime('%Y-%m-%d %H:%M')
    best['capital']       = cfg['capital']
    best['market_status'] = market_sig

    RESULT_FILE.write_text(
        json.dumps(best, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    log.info(f'Kaydedildi: {RESULT_FILE}')

    # Firebase'e gridRec yaz — tüm cihazlar HTML cache'inden bağımsız güncel veriyi alır
    try:
        fb_url = 'https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app/gridtracker/gridRec.json'
        payload_bytes = json.dumps(best, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(fb_url, data=payload_bytes, method='PUT')
        req.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(req, timeout=10):
            pass
        log.info(f'Firebase gridRec guncellendi ({best["symbol"]})')
    except Exception as e:
        log.warning(f'Firebase gridRec write hatasi: {e}')

    # -------------------------------------------------------------------------
    # AKTIF HİSSE ANALİZİ + scoreHistory
    # -------------------------------------------------------------------------
    today_str = datetime.now().strftime('%Y-%m-%d')

    def update_score_history(symbol, grid_sc, final_sc, price_val):
        """Firebase scoreHistory guncellemesi — sembol basina max SCORE_HIST_MAX kayit."""
        hist = fb_get(f'scoreHistory/{symbol}') or []
        if not isinstance(hist, list):
            hist = []
        # Bugunku kayit varsa guncelle, yoksa ekle
        if hist and hist[-1].get('date') == today_str:
            hist[-1] = {'date': today_str, 'gs': round(grid_sc, 2),
                        'fs': round(final_sc, 2), 'price': round(price_val, 2)}
        else:
            hist.append({'date': today_str, 'gs': round(grid_sc, 2),
                         'fs': round(final_sc, 2), 'price': round(price_val, 2)})
        if len(hist) > SCORE_HIST_MAX:
            hist = hist[-SCORE_HIST_MAX:]
        fb_put(f'scoreHistory/{symbol}', hist)
        log.info(f'scoreHistory guncellendi: {symbol} ({len(hist)} kayit)')

    # En iyi hissenin scoreHistory'sini guncelle
    update_score_history(best['symbol'], best['grid_score'], best['final_score'], best['price'])

    # Aktif hisseyi Firebase'den oku
    active_sym = None
    try:
        settings_data = fb_get('settings')
        if settings_data and isinstance(settings_data, dict):
            gc = settings_data.get('gridCalc', {})
            if isinstance(gc, dict):
                active_sym = (gc.get('symbol') or '').upper().strip()
    except Exception as e:
        log.warning(f'Aktif hisse okunamadi: {e}')

    if active_sym and active_sym != best['symbol']:
        log.info(f'Aktif hisse analiz ediliyor: {active_sym}')
        active_ticker = active_sym + '.IS'
        active_r = analyze_stock(active_ticker, cfg, min_score=0)
        if active_r:
            # Final skorunu tek hisse normalizasyonu ile hesapla
            active_r['final_score'] = round(active_r['grid_score'] * market_mult, 3)
            active_r.pop('_raw_profit', None)
            active_r['updated_at']    = datetime.now().strftime('%Y-%m-%d %H:%M')
            active_r['market_status'] = market_sig
            # Aktif hissenin scoreHistory'sini guncelle
            update_score_history(active_r['symbol'], active_r['grid_score'],
                                 active_r['final_score'], active_r['price'])
            # gridRecActive yaz
            if fb_put('gridRecActive', active_r):
                log.info(f'Firebase gridRecActive guncellendi ({active_sym})')
            else:
                log.warning(f'Firebase gridRecActive write hatasi')
            # ── Karar + ntfy bildirimi ──
            _notify_verdict(cfg, active_r, best, active_sym)
        else:
            log.info(f'Aktif hisse analiz sonucu yok: {active_sym} (dusuk skor veya veri)')
            # Yine de mevcut fiyat+skor bilgisini almaya calis (sadece skor icin)
            try:
                import yfinance as _yf
                _df = _yf.Ticker(active_ticker).history(period='30d', interval='1d', auto_adjust=True)
                if _df is not None and len(_df) > 0:
                    _price = float(_df['Close'].iloc[-1])
                    log.info(f'{active_sym} son fiyat: {_price:.2f} (tam analiz yapılamadı)')
            except Exception:
                pass
    elif active_sym == best['symbol']:
        # Aktif hisse zaten en iyi hisse — gridRecActive = gridRec kopyasi
        active_copy = dict(best)
        if fb_put('gridRecActive', active_copy):
            log.info(f'Firebase gridRecActive = gridRec (aktif == en iyi: {active_sym})')
        # Aktif == en iyi: sadece düşük skor varsa bildir
        _notify_verdict(cfg, active_copy, None, active_sym)
    else:
        log.info('Aktif hisse ayarlanmamis, gridRecActive atlanıyor.')

    # bist_tracker.html içindeki window.__GRID_REC__ bloğunu güncelle (GitHub Pages uyumu)
    html_file = SCRIPT_DIR / 'bist_tracker.html'
    if html_file.exists():
        try:
            html = html_file.read_text(encoding='utf-8')
            rec_json = json.dumps(best, ensure_ascii=False, separators=(',', ':'))
            new_block = (
                '                                // GRID_REC_START\n'
                f'        window.__GRID_REC__ = {rec_json};\n'
                '                                // GRID_REC_END'
            )
            import re as _re
            pattern = r'// GRID_REC_START.*?// GRID_REC_END'
            updated, n = _re.subn(pattern, new_block, html, flags=_re.DOTALL)
            if n:
                html_file.write_text(updated, encoding='utf-8')
                log.info(f'bist_tracker.html __GRID_REC__ guncellendi ({best["symbol"]})')
            else:
                log.warning('bist_tracker.html: GRID_REC_START/END blogu bulunamadi')
        except Exception as e:
            log.warning(f'HTML guncelleme hatasi: {e}')

    log.info('==========================================')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--test',  action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try:
        run(dry_run=args.test, force=args.force)
    except KeyboardInterrupt:
        log.info('Durduruldu.')
    except Exception as e:
        log.exception(f'Hata: {e}')
        sys.exit(1)
