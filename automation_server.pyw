#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
automation_server.py
====================
Sabah otomasyonu ayarlarını yönetmek için yerel API sunucusu.
Varsayılan port: 5050

Kullanım:
  python automation_server.py          # Sunucuyu başlat
  python automation_server.py --setup  # Görev zamanlayıcıya ekle (Windows login'de otomatik başlar)
"""

import sys, os, re, json, subprocess, argparse, configparser, threading, time, urllib.request
from pathlib import Path
from datetime import date

for _pkg in ['pywebpush']:
    try:
        __import__(_pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg])

FIREBASE_URL = 'https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app'

if sys.platform == 'win32':
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr is not None:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

for _pkg in ['holidays', 'openpyxl']:
    try:
        __import__(_pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg])

# FLASK KALDIRILDI (2026-07-14): Kaspersky davranış koruması, werkzeug tabanlı
# headless sunucuyu bind'dan ~10 sn sonra iz bırakmadan öldürüyordu. server.py
# aynı makinede stdlib http.server ile (0.0.0.0:5050) aylardır sorunsuz →
# aynı sisteme geçirildi (ThreadingHTTPServer + Handler).
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

SCRIPT_DIR  = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / 'morning_config.ini'
TASK_NAME   = 'MatriksIQ_Sabah_Otomasyonu'
PORT        = 5051


def _read_cfg():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE, encoding='utf-8')
    return cfg


def _write_cfg(cfg):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        cfg.write(f)


def _wake_time(time_str):
    """Verilen saatten 5 dakika önce uyandırma saatini hesaplar."""
    h, m = map(int, time_str.split(':'))
    m -= 5
    if m < 0:
        m += 60
        h -= 1
    return f'{h:02d}:{m:02d}'


def _update_task(time_str):
    """Task Scheduler görevini siler ve yeni saatle yeniden oluşturur."""
    python = str(Path(sys.executable).parent / 'pythonw.exe')
    script = str(SCRIPT_DIR / 'morning_automation.pyw')

    # Varsa sil
    subprocess.run(
        f'schtasks /Delete /TN "{TASK_NAME}" /F',
        shell=True, capture_output=True
    )

    # Yeni görevi oluştur (Pzt-Cum, belirlenen saatte)
    cmd = (
        f'schtasks /Create /TN "{TASK_NAME}" '
        f'/TR "\\"{python}\\" \\"{script}\\"" '
        f'/SC WEEKLY /D MON,TUE,WED,THU,FRI '
        f'/ST {time_str} /F'
    )
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
    return result.returncode == 0, result.stdout + result.stderr


# ── API işleyicileri (framework'süz; her biri (status, payload) döner) ──────
def api_get_settings():
    cfg = _read_cfg()
    time_str = cfg.get('schedule', 'time', fallback='09:15')
    return 200, {
        'time': time_str,
        'wake_time': _wake_time(time_str),
        'task_name': TASK_NAME,
    }


def api_save_settings(data):
    time_str = (data or {}).get('time', '').strip()

    if not re.match(r'^\d{2}:\d{2}$', time_str):
        return 400, {'error': 'Geçersiz saat formatı (HH:MM bekleniyor)'}

    h, m = map(int, time_str.split(':'))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return 400, {'error': 'Saat değeri geçersiz'}

    # Config güncelle
    cfg = _read_cfg()
    if 'schedule' not in cfg:
        cfg.add_section('schedule')
    cfg.set('schedule', 'time', time_str)
    _write_cfg(cfg)

    # Task Scheduler güncelle
    ok, msg = _update_task(time_str)
    wake = _wake_time(time_str)

    return 200, {
        'success': True,
        'time': time_str,
        'wake_time': wake,
        'task_ok': ok,
        'task_msg': msg.strip(),
    }


def api_holidays(year):
    import holidays as _hol
    tr = _hol.Turkey(years=year)
    items = sorted([{'date': str(d), 'name': name} for d, name in tr.items()],
                   key=lambda x: x['date'])
    return 200, items


def api_sr(symbol, mode='main'):
    try:
        ticker = symbol.upper() + '.IS'
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=60d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        q = data['chart']['result'][0]['indicators']['quote'][0]
        prices = [(h, l, c) for h, l, c in zip(q['high'], q['low'], q['close']) if h and l and c]
        if len(prices) < 10:
            return 400, {'error': 'Yetersiz veri'}
        current = prices[-1][2]
        if mode in ('swing', 'swing3', 'swing5'):
            # Swing low/high tespiti
            W, n = 2, len(prices)
            swing_highs, swing_lows = [], []
            for i in range(W, n - W):
                h, l, _ = prices[i]
                if all(h >= prices[i+j][0] for j in range(-W, W+1) if j != 0):
                    swing_highs.append(round(h, 2))
                if all(l <= prices[i+j][1] for j in range(-W, W+1) if j != 0):
                    swing_lows.append(round(l, 2))
            supports    = sorted([p for p in swing_lows if p < current * 0.998], reverse=True)
            resistances = sorted([p for p in swing_highs if p > current * 1.002])
            idx = 4 if mode == 'swing5' else 2 if mode == 'swing3' else 0
            support    = supports[idx]    if len(supports)    > idx else (supports[-1]    if supports    else round(min(p[1] for p in prices[-20:]), 2))
            resistance = resistances[idx] if len(resistances) > idx else (resistances[-1] if resistances else round(max(p[0] for p in prices[-20:]), 2))
        else:
            support    = round(min(p[1] for p in prices), 2)
            resistance = round(max(p[0] for p in prices), 2)
        return 200, {
            'support': support, 'resistance': resistance,
            'current': round(current, 2),
            'supports': [support], 'resistances': [resistance],
        }
    except Exception as e:
        return 500, {'error': str(e)}


def api_atr(symbol):
    try:
        import urllib.request as ur, json as _json
        ticker = symbol.upper() + '.IS'
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=10d'
        req = ur.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with ur.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read())
        result = data['chart']['result'][0]
        meta   = result.get('meta', {})
        quote  = result['indicators']['quote'][0]
        highs  = [v for v in quote['high']  if v is not None][-7:]
        lows   = [v for v in quote['low']   if v is not None][-7:]
        closes = [v for v in quote['close'] if v is not None]
        n = min(len(highs), len(lows))
        if n < 1:
            return 400, {'error': 'Yetersiz veri'}
        atr = sum(highs[i] - lows[i] for i in range(n)) / n
        # regularMarketPrice güncel fiyat (piyasa açıksa anlık, kapalıysa son kapanış)
        price = meta.get('regularMarketPrice') or (closes[-1] if closes else None)
        if price:
            # Firebase'e yaz — telefon/GitHub Pages buradan okur
            def _push():
                try:
                    pl = _json.dumps({'price': round(price,2), 'ts': int(time.time())}).encode()
                    rq = ur.Request(f'{FIREBASE_URL}/gridtracker/livePrices/{symbol.upper()}.json',
                                    data=pl, method='PUT',
                                    headers={'Content-Type':'application/json'})
                    ur.urlopen(rq, timeout=5)
                except: pass
            threading.Thread(target=_push, daemon=True).start()
        return 200, {'atr': round(atr, 4), 'price': round(price, 2) if price else None, 'days': n}
    except Exception as e:
        return 500, {'error': str(e)}


# ── Task Scheduler setup ───────────────────────────────────
def setup_autostart():
    """Sunucuyu Windows başlangıcında otomatik başlatmak için Registry'e ekler (admin gerekmez)."""
    import winreg
    pythonw = str(Path(sys.executable).parent / 'pythonw.exe')
    script  = str(Path(__file__).resolve())
    value   = f'"{pythonw}" "{script}"'
    key_path = r'Software\Microsoft\Windows\CurrentVersion\Run'
    try:
        # KOŞULLU YAZ: değer zaten doğruysa DOKUNMA. Her açılışta Run kaydı
        # yazmak + saniyeler içinde port açmak = zararlı-davranış imzası →
        # Kaspersky süreci ~10 sn'de öldürüyordu (2026-07-14 tespiti).
        try:
            rk = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
            cur, _ = winreg.QueryValueEx(rk, 'GridTrackerServer')
            winreg.CloseKey(rk)
        except Exception:
            cur = None
        if cur == value:
            return   # kayıt güncel — yazma, Kaspersky'yi tetikleme
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, 'GridTrackerServer', 0, winreg.REG_SZ, value)
        winreg.CloseKey(key)
        print('Otomatik başlatma Registry\'e eklendi.')
    except Exception as e:
        print(f'Registry hatası: {e}')


# ── Web Push ──────────────────────────────────────────
VAPID_KEYS_FILE = SCRIPT_DIR / 'vapid_keys.json'
VAPID_CLAIMS    = {'sub': 'mailto:admin@gridtracker.local'}

def _load_vapid():
    try:
        return json.loads(VAPID_KEYS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return None

def send_push_to_all(title, body, tag='gridtracker'):
    """Firebase'deki tüm push subscription'larına bildirim gönderir."""
    keys = _load_vapid()
    if not keys:
        print('[Push] VAPID keys bulunamadı')
        return
    try:
        from pywebpush import webpush, WebPushException
        # Tüm subscription'ları çek
        req = urllib.request.urlopen(
            f'{FIREBASE_URL}/gridtracker/pushSubscriptions.json', timeout=10)
        subs = json.loads(req.read().decode())
        if not subs or not isinstance(subs, dict):
            print('[Push] Kayıtlı cihaz yok')
            return
        payload = json.dumps({'title': title, 'body': body, 'tag': tag})
        sent = 0
        for sub_key, sub_data in subs.items():
            try:
                if isinstance(sub_data, str):
                    sub_data = json.loads(sub_data)
                webpush(
                    subscription_info=sub_data,
                    data=payload,
                    vapid_private_key=keys['privateKey'],
                    vapid_claims=VAPID_CLAIMS,
                    ttl=86400,
                    headers={'urgency': 'high'}
                )
                sent += 1
            except WebPushException as e:
                status = e.response.status_code if e.response else 0
                if status == 410:
                    # Subscription kalıcı olarak silindi (410) — Firebase'den kaldır
                    try:
                        urllib.request.urlopen(urllib.request.Request(
                            f'{FIREBASE_URL}/gridtracker/pushSubscriptions/{sub_key}.json',
                            method='DELETE'
                        ), timeout=5)
                    except Exception:
                        pass
                print(f'[Push] {sub_key[:12]}... hata: {e}')
            except Exception as e:
                print(f'[Push] Gönderim hatası: {e}')
        print(f'[Push] Gönderildi: {sent}/{len(subs)} cihaz — {title}')
    except Exception as e:
        print(f'[Push] Genel hata: {e}')


def _check_push_queue():
    """Firebase pushQueue'yu kontrol et, yeni bildirim varsa gönder."""
    try:
        req = urllib.request.urlopen(
            f'{FIREBASE_URL}/gridtracker/pushQueue.json', timeout=10)
        queue = json.loads(req.read().decode())
        if not queue or not isinstance(queue, dict):
            return
        for tag, item in queue.items():
            if not isinstance(item, dict):
                continue
            ts = item.get('ts', 0)
            # 60 saniyeden eski bildirimleri atla (stale)
            if time.time()*1000 - ts > 60000:
                continue
            title = item.get('title', 'GridTracker')
            body  = item.get('body', '')
            threading.Thread(
                target=send_push_to_all,
                args=(title, body, tag),
                daemon=True
            ).start()
        # Queue'yu temizle
        urllib.request.urlopen(urllib.request.Request(
            f'{FIREBASE_URL}/gridtracker/pushQueue.json',
            data=b'null', method='PUT',
            headers={'Content-Type': 'application/json'}
        ), timeout=5)
    except Exception:
        pass


# ── HTTP Handler (server.py ile aynı düzen: stdlib, CORS'lu JSON) ──────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Private-Network', 'true')

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors_headers()
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u     = urlparse(self.path)
        path  = u.path
        qs    = parse_qs(u.query)
        parts = path.strip('/').split('/')
        try:
            if path == '/api/health':
                return self.send_json(200, {'ok': True, 'port': PORT})
            if path == '/api/morning-settings':
                return self.send_json(*api_get_settings())
            if len(parts) == 3 and parts[0] == 'api' and parts[1] == 'holidays':
                try:
                    year = int(parts[2])
                except ValueError:
                    return self.send_json(400, {'error': 'Geçersiz yıl'})
                return self.send_json(*api_holidays(year))
            if len(parts) == 3 and parts[0] == 'api' and parts[1] == 'sr':
                mode = (qs.get('mode') or ['main'])[0]
                return self.send_json(*api_sr(parts[2], mode))
            if len(parts) == 3 and parts[0] == 'api' and parts[1] == 'atr':
                return self.send_json(*api_atr(parts[2]))
            return self.send_json(404, {'error': 'Bulunamadı'})
        except Exception as e:
            try:
                self.send_json(500, {'error': str(e)})
            except Exception:
                pass

    def do_POST(self):
        try:
            ln   = int(self.headers.get('Content-Length') or 0)
            raw  = self.rfile.read(ln) if ln else b''
            try:
                data = json.loads(raw.decode('utf-8')) if raw else {}
            except Exception:
                data = {}
            if self.path.split('?')[0] == '/api/morning-settings':
                return self.send_json(*api_save_settings(data))
            if self.path.split('?')[0] == '/api/notify':
                title = data.get('title', 'GridTracker')
                body  = data.get('body', '')
                tag   = data.get('tag', 'gridtracker')
                threading.Thread(target=send_push_to_all,
                                 args=(title, body, tag), daemon=True).start()
                return self.send_json(200, {'ok': True})
            return self.send_json(404, {'error': 'Bulunamadı'})
        except Exception as e:
            try:
                self.send_json(500, {'error': str(e)})
            except Exception:
                pass


def fb_write(path, data):
    """Firebase Realtime Database'e REST API ile veri yazar."""
    url = f'{FIREBASE_URL}/{path}.json'
    payload = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, data=payload, method='PUT')
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())


def fetch_price(symbol):
    """
    Anlık fiyat çeker.
    Önce Excel (MatriksIQ DDE - anlık), yoksa Yahoo Finance (15dk gecikmeli).
    """
    try:
        from price_reader import get_price
        price, _ = get_price(symbol.upper())
        if price and price > 0:
            return round(price, 2)
    except Exception:
        pass
    # Yahoo fallback
    try:
        ticker = symbol.upper() + '.IS'
        url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        closes = [v for v in data['chart']['result'][0]['indicators']['quote'][0]['close'] if v is not None]
        return round(closes[-1], 2) if closes else None
    except Exception:
        return None


def _watcher_loop():
    """Firebase izleyici ana döngüsü — tek iterasyon."""
    last_sched = getattr(_watcher_loop, '_last_sched', None)
    last_price_update = getattr(_watcher_loop, '_last_price_update', 0)

    try:
        # --- Schedule sync ---
        req = urllib.request.urlopen(
            f'{FIREBASE_URL}/settings/schedule_time.json', timeout=10)
        val = json.loads(req.read().decode())
        if val and isinstance(val, str) and re.match(r'^\d{2}:\d{2}$', val) and val != last_sched:
            cfg = _read_cfg()
            current = cfg.get('schedule', 'time', fallback='09:15')
            if val != current:
                if 'schedule' not in cfg:
                    cfg.add_section('schedule')
                cfg.set('schedule', 'time', val)
                _write_cfg(cfg)
                ok, _ = _update_task(val)
                print(f'[Firebase] Saat güncellendi: {val}  (görev: {"OK" if ok else "HATA"})')
            _watcher_loop._last_sched = val
    except Exception:
        pass

    try:
        # --- Anlık fiyat talepleri (priceRequests) ---
        req3 = urllib.request.urlopen(
            f'{FIREBASE_URL}/gridtracker/priceRequests.json', timeout=10)
        requests_data = json.loads(req3.read().decode())
        if requests_data and isinstance(requests_data, dict):
            for sym in list(requests_data.keys()):
                try:
                    price = fetch_price(sym)
                    if price:
                        fb_write('gridtracker/livePrices/' + sym, {
                            'price': price,
                            'ts': int(time.time())
                        })
                        print(f'[Talep] {sym}: {price} ₺')
                except Exception as e:
                    print(f'[Talep] {sym} hatası: {e}')
            fb_write('gridtracker/priceRequests', {})
    except Exception:
        pass

    # --- Hisse fiyatı güncelle (her 2 dakikada bir) ---
    if time.time() - last_price_update >= 120:
        try:
            req2 = urllib.request.urlopen(
                f'{FIREBASE_URL}/gridtracker/settings/gridCalc.json', timeout=10)
            gc = json.loads(req2.read().decode())
            symbol = (gc or {}).get('symbol', '').strip().upper()
            if symbol:
                price = fetch_price(symbol)
                if price:
                    fb_write('gridtracker/livePrices/' + symbol, {
                        'price': price,
                        'ts': int(time.time())
                    })
                    print(f'[Fiyat] {symbol}: {price} ₺')
        except Exception as e:
            print(f'[Fiyat] Güncelleme hatası: {e}')
        _watcher_loop._last_price_update = time.time()

    # --- Push queue kontrol ---
    _check_push_queue()

    # --- Heartbeat yaz ---
    try:
        fb_write('gridtracker/serverHeartbeat', {'ts': int(time.time())})
    except Exception as e:
        print(f'[Heartbeat] Hata: {e}')


_watcher_loop._last_sched = None
_watcher_loop._last_price_update = 0


def _fetch_and_cache_sr(symbols):
    """Her sembol için 3 mod SR verisini Yahoo'dan çekip Firebase'e yazar."""
    for sym in symbols:
        for mode in ('main', 'swing5', 'swing3'):
            try:
                ticker = sym + '.IS'
                url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=60d'
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                q = data['chart']['result'][0]['indicators']['quote'][0]
                meta = data['chart']['result'][0].get('meta', {})
                prices = [(h, l, c) for h, l, c in zip(q['high'], q['low'], q['close']) if h and l and c]
                if len(prices) < 5: continue
                current = meta.get('regularMarketPrice') or prices[-1][2]
                # Fiyatı livePrices'a yaz (henüz yazılmadıysa)
                if mode == 'main':
                    urllib.request.urlopen(urllib.request.Request(
                        f'{FIREBASE_URL}/gridtracker/livePrices/{sym}.json',
                        data=json.dumps({'price': round(current, 2), 'ts': int(time.time())}).encode(),
                        method='PUT', headers={'Content-Type': 'application/json'}
                    ), timeout=5)
                if mode == 'main':
                    support = round(min(p[1] for p in prices), 2)
                    resistance = round(max(p[0] for p in prices), 2)
                else:
                    W, n = 2, len(prices)
                    sh, sl = [], []
                    for i in range(W, n - W):
                        h, l, _ = prices[i]
                        if all(h >= prices[i+j][0] for j in range(-W, W+1) if j != 0): sh.append(round(h, 2))
                        if all(l <= prices[i+j][1] for j in range(-W, W+1) if j != 0): sl.append(round(l, 2))
                    idx = 4 if mode == 'swing5' else 2
                    sups = sorted([p for p in sl if p < current * 0.998], reverse=True)
                    ress = sorted([p for p in sh if p > current * 1.002])
                    support = sups[idx] if len(sups) > idx else (sups[-1] if sups else round(min(p[1] for p in prices[-20:]), 2))
                    resistance = ress[idx] if len(ress) > idx else (ress[-1] if ress else round(max(p[0] for p in prices[-20:]), 2))
                urllib.request.urlopen(urllib.request.Request(
                    f'{FIREBASE_URL}/gridtracker/srCache/{sym}_{mode}.json',
                    data=json.dumps({'support': support, 'resistance': resistance, 'ts': int(time.time())}).encode(),
                    method='PUT', headers={'Content-Type': 'application/json'}
                ), timeout=5)
                print(f'[SR] {sym}/{mode}: {support} / {resistance}')
            except Exception as e:
                print(f'[SR] {sym}/{mode} hata: {e}')


def atr_file_watcher():
    """Masaüstünde 3*.xlsx belirince otomatik Firebase'e yaz ve dosyayı sil."""
    desktop_dir = Path.home() / 'Desktop'
    print('[ATR] Dosya izleyici başladı — masaüstünde 3*.xlsx bekleniyor...')
    while True:
        try:
            matches = list(desktop_dir.glob('3*.xlsx'))
            desktop = matches[0] if matches else None
            if desktop and desktop.exists():
                time.sleep(1)  # Dosyanın tam yazılmasını bekle
                import openpyxl
                wb = openpyxl.load_workbook(desktop, read_only=True, data_only=True)
                ws = wb.active
                rows = list(ws.iter_rows(values_only=True))
                wb.close()
                if len(rows) >= 2:
                    headers = [str(h).strip() if h else '' for h in rows[0]]
                    # ATR dosyası olup olmadığını doğrula — Sembol + en az bir ATR sütunu şart
                    atr_cols = {'ATR - 60DK', 'ATR - 240DK', 'ATR - DAY', 'ATR - WEEK'}
                    has_sembol = 'Sembol' in headers
                    has_atr = bool(atr_cols & set(headers))
                    if not (has_sembol and has_atr):
                        print(f'[ATR] {desktop.name} ATR dosyası değil, atlandı.')
                        continue
                    saved = []
                    for row in rows[1:]:
                        if not any(row): continue
                        d = dict(zip(headers, row))
                        sym = str(d.get('Sembol') or '').upper().strip()
                        if not sym: continue
                        def _v(k):
                            v = d.get(k)
                            return round(float(v), 6) if v is not None else None
                        atr60  = _v('ATR - 60DK')
                        atr240 = _v('ATR - 240DK')
                        atrDay = _v('ATR - DAY')
                        atrWeek= _v('ATR - WEEK')
                        composite = round(((atr60 or 0)*2 + (atr240 or 0)*3 + (atrDay or 0)*4 + (atrWeek or 0)*1) / 10, 6)
                        # Fiyat sütunlarını dene (MatriksIQ formatı)
                        price = None
                        for pcol in ('Son', 'Son Fiyat', 'Fiyat', 'Kapanış', 'Close', 'Last'):
                            v = d.get(pcol)
                            if v is not None:
                                try: price = round(float(v), 2); break
                                except: pass
                        payload = json.dumps({
                            'atr60': atr60, 'atr240': atr240,
                            'atrDay': atrDay, 'atrWeek': atrWeek,
                            'composite': composite, 'ts': int(time.time()*1000)
                        }).encode()
                        urllib.request.urlopen(urllib.request.Request(
                            f'{FIREBASE_URL}/gridtracker/settings/atrCache/{sym}.json',
                            data=payload, method='PUT',
                            headers={'Content-Type': 'application/json'}
                        ), timeout=8)
                        if price:
                            urllib.request.urlopen(urllib.request.Request(
                                f'{FIREBASE_URL}/gridtracker/livePrices/{sym}.json',
                                data=json.dumps({'price': price, 'ts': int(time.time())}).encode(),
                                method='PUT', headers={'Content-Type': 'application/json'}
                            ), timeout=8)
                        saved.append(sym)
                    # SR verisini arka planda çek ve Firebase'e yaz
                    threading.Thread(target=_fetch_and_cache_sr, args=(saved,), daemon=True).start()
                    desktop.unlink()
                    print(f'[ATR] Firebase\'e kaydedildi: {", ".join(saved)} — dosya silindi.')
        except Exception as e:
            print(f'[ATR] Hata: {e}')
        time.sleep(3)


def firebase_watcher():
    """Firebase izleyici — çökse bile kendini yeniden başlatır."""
    print('[Firebase] İzleyici başladı.')
    while True:
        try:
            _watcher_loop()
        except Exception as e:
            print(f'[Firebase] Beklenmedik hata, devam ediliyor: {e}')
        time.sleep(10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Otomasyon Ayarlar Sunucusu')
    parser.add_argument('--setup', action='store_true',
                        help='Windows oturumunda otomatik başlatmak için görev ekle')
    args = parser.parse_args()

    if args.setup:
        setup_autostart()
    else:
        # Port doluysa SESSİZCE çık — eski instance çalışıyor demektir.
        # (Eski netstat|taskkill shell komutu KALDIRILDI: süreç öldürme +
        # Registry yazma + port açma üçlüsü Kaspersky davranış imzasıydı.
        # Çift kopya yönetimi artık health_watchdog dedup'ında.)
        try:
            import socket as _sock
            with _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM) as _s:
                if _s.connect_ex(('127.0.0.1', PORT)) == 0:
                    print(f'[Başlangıç] Port {PORT} zaten kullanımda — çıkılıyor.')
                    sys.exit(0)
        except SystemExit:
            raise
        except Exception:
            pass
        # Windows oturumunda otomatik başlat (yalnız kayıt eksik/yanlışsa yazar)
        setup_autostart()
        # Firebase izleyiciyi arka planda başlat
        t = threading.Thread(target=firebase_watcher, daemon=True)
        t.start()
        # ATR dosya izleyiciyi arka planda başlat
        t2 = threading.Thread(target=atr_file_watcher, daemon=True)
        t2.start()
        # Tailscale IP'yi bul, yoksa yerel IP kullan
        try:
            import socket as _sock2
            tailscale_ip = None
            for iface_ip in _sock2.gethostbyname_ex(_sock2.gethostname())[2]:
                if iface_ip.startswith('100.'):
                    tailscale_ip = iface_ip
                    break
            s2 = _sock2.socket(_sock2.AF_INET, _sock2.SOCK_DGRAM)
            s2.connect(('8.8.8.8', 80))
            local_ip = tailscale_ip or s2.getsockname()[0]
            s2.close()
            info_data = json.dumps({'ip': local_ip, 'port': PORT, 'ts': int(time.time())}).encode()
            req2 = urllib.request.Request(
                f'{FIREBASE_URL}/gridtracker/serverInfo.json',
                data=info_data, method='PUT',
                headers={'Content-Type': 'application/json'}
            )
            urllib.request.urlopen(req2, timeout=5)
            print(f'[Firebase] Sunucu IP yazıldı: {local_ip}:{PORT}')
        except Exception as e:
            print(f'[Firebase] IP yazılamadı: {e}')
        print(f'Otomasyon ayarlar sunucusu başlatılıyor: http://0.0.0.0:{PORT}')
        print(f'Firebase izleyici aktif (10s aralık)')
        server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
        server.serve_forever()
