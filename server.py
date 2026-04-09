#!/usr/bin/env python3
"""
GridTracker Server - port 5050
- ATR_Sonuc.xlsx ve Destek_Direc_Seviyeleri.xlsx okur
- GET /api/stock/{SYM}  → hisse verisi (fiyat + ATR + destek/direnç)
- GET /api/all          → tüm hisseler
- GET /api/health       → durum
- POST /api/notify      → push bildirimi gönder
- GET /                 → bist_tracker.html
- Arka planda 60s'de bir Firebase'e push eder
Stdlib only + openpyxl (otomatik install edilir)
"""
import subprocess, sys

for _pkg in ['openpyxl', 'pywebpush']:
    try:
        __import__(_pkg.replace('-', '_'))
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg, '-q'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

from openpyxl import load_workbook
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.request, json, socket, threading, time, os

FIREBASE_URL = 'https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app'
PORT = 5050
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ATR_FILE = os.path.join(BASE_DIR, 'ATR_Sonuc.xlsx')
DD_FILE  = os.path.join(BASE_DIR, 'Destek_Direc_Seviyeleri.xlsx')
VAPID_FILE = os.path.join(BASE_DIR, 'vapid_keys.json')

VAPID_CLAIMS = {'sub': 'mailto:admin@gridtracker.local'}

# Bellekte tutulan veri
_stocks = {}
_stocks_ts = 0
_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Excel okuma
# ---------------------------------------------------------------------------

def _val(cell):
    v = cell.value
    if v is None: return None
    try: return float(v)
    except: return str(v).strip()

def read_excel():
    atr = {}
    dd  = {}

    # ATR_Sonuc.xlsx
    if os.path.exists(ATR_FILE):
        try:
            wb = load_workbook(ATR_FILE, data_only=True, read_only=True)
            ws = wb[wb.sheetnames[0]]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row[0]: continue
                sym = str(row[0]).strip().upper()
                if not sym: continue
                # Sütun sırası: Sembol, Periyod, Birim, Anlık Fiyat, ATR 5dk, ATR 60dk, ATR 120dk, ATR 240dk, ATR Günlük, ATR Haftalık, ATR Ortalama
                vals = list(row)
                atr[sym] = {
                    'price':        _safe(vals[3]),
                    'atr_5dk':      _safe(vals[4]),
                    'atr_60dk':     _safe(vals[5]),
                    'atr_120dk':    _safe(vals[6]),
                    'atr_240dk':    _safe(vals[7]),
                    'atr_gunluk':   _safe(vals[8]),
                    'atr_haftalik': _safe(vals[9]),
                    'atr_ort':      _safe(vals[10]),
                }
            wb.close()
        except Exception as e:
            print(f'[ATR] okuma hatası: {e}')

    # Destek_Direc_Seviyeleri.xlsx
    if os.path.exists(DD_FILE):
        try:
            wb = load_workbook(DD_FILE, data_only=True, read_only=True)
            ws = wb[wb.sheetnames[0]]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row[0]: continue
                sym = str(row[0]).strip().upper()
                if not sym: continue
                # Sütun sırası: Sembol, Periyod, Birim, Hisse Fiyatı, Yakın Destek, Yakın Direnç, Orta Destek, Orta Direnç, Uzak Destek, Uzak Direnç, Durum, Trend Gücü
                vals = list(row)
                dd[sym] = {
                    'price2':    _safe(vals[3]),
                    'yakin_sup': _safe(vals[4]),
                    'yakin_res': _safe(vals[5]),
                    'orta_sup':  _safe(vals[6]),
                    'orta_res':  _safe(vals[7]),
                    'sup':       _safe(vals[8]),
                    'res':       _safe(vals[9]),
                    'durum':     str(vals[10] or '').strip(),
                    'trend':     str(vals[11] or '').strip(),
                }
            wb.close()
        except Exception as e:
            print(f'[DD] okuma hatası: {e}')

    # Birleştir
    syms = set(atr) | set(dd)
    result = {}
    for sym in syms:
        entry = {'ts': int(time.time())}
        entry.update(atr.get(sym, {}))
        entry.update(dd.get(sym, {}))
        # Fiyat: ATR dosyasındaki Anlik Fiyat öncelikli, yoksa DD dosyasındaki
        if entry.get('price') is None and entry.get('price2') is not None:
            entry['price'] = entry['price2']
        entry.pop('price2', None)
        result[sym] = entry
    return result

def _safe(v):
    if v is None: return None
    try: return round(float(v), 4)
    except: return None

# ---------------------------------------------------------------------------
# Firebase
# ---------------------------------------------------------------------------

def firebase_put(path, data):
    try:
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            f'{FIREBASE_URL}/{path}.json', data=body, method='PUT',
            headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f'[Firebase] hata: {e}')

def get_server_ip():
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ip.startswith('100.'):
                return ip
    except: pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except: return '127.0.0.1'

# ---------------------------------------------------------------------------
# Arka plan thread: Excel oku → belleği güncelle → Firebase'e push
# ---------------------------------------------------------------------------

def _bg_loop():
    while True:
        try:
            stocks = read_excel()
            ts = int(time.time())
            with _lock:
                _stocks.clear()
                _stocks.update(stocks)
                global _stocks_ts
                _stocks_ts = ts
            # Firebase'e yaz
            firebase_put('gridtracker/stocks', stocks)
            firebase_put('gridtracker/stocks_ts', ts)
        except Exception as e:
            print(f'[BG] hata: {e}')
        time.sleep(60)

def _push_queue_loop():
    """Her 10 saniyede bir Firebase pushQueue kontrol et."""
    while True:
        try:
            _check_push_queue()
        except Exception as e:
            print(f'[PushQueue] hata: {e}')
        time.sleep(10)

# ---------------------------------------------------------------------------
# Push Bildirimleri
# ---------------------------------------------------------------------------

def _load_vapid():
    try:
        with open(VAPID_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f'[Push] VAPID yüklenemedi: {e}')
        return None

def send_push_to_all(title, body, tag='gridtracker'):
    keys = _load_vapid()
    if not keys:
        print('[Push] VAPID anahtarı yok, bildirim atlandı.')
        return
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print('[Push] pywebpush yüklü değil.')
        return
    try:
        req = urllib.request.Request(
            f'{FIREBASE_URL}/gridtracker/pushSubscriptions.json')
        resp = urllib.request.urlopen(req, timeout=10)
        subs = json.loads(resp.read().decode())
    except Exception as e:
        print(f'[Push] Aboneler alınamadı: {e}')
        return
    if not subs or not isinstance(subs, dict):
        print('[Push] Kayıtlı abone yok.')
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
                vapid_claims=VAPID_CLAIMS
            )
            sent += 1
        except WebPushException as e:
            status = getattr(e.response, 'status_code', None) if e.response else None
            if status in (404, 410):
                # Geçersiz abone — sil
                try:
                    del_req = urllib.request.Request(
                        f'{FIREBASE_URL}/gridtracker/pushSubscriptions/{sub_key}.json',
                        method='DELETE')
                    urllib.request.urlopen(del_req, timeout=5)
                    print(f'[Push] Geçersiz abone silindi: {sub_key}')
                except Exception:
                    pass
            else:
                print(f'[Push] WebPush hatası [{sub_key}]: {e}')
        except Exception as e:
            print(f'[Push] Beklenmeyen hata [{sub_key}]: {e}')
    print(f'[Push] Bildirim gönderildi: {sent} abone — {title}')

def _check_push_queue():
    """Firebase pushQueue'daki bildirimleri gönder ve sil."""
    try:
        req = urllib.request.Request(
            f'{FIREBASE_URL}/gridtracker/pushQueue.json')
        resp = urllib.request.urlopen(req, timeout=10)
        queue = json.loads(resp.read().decode())
        if not queue or not isinstance(queue, dict):
            return
        for tag, item in queue.items():
            if not isinstance(item, dict):
                continue
            title = item.get('title', 'GridTracker')
            body  = item.get('body', '')
            send_push_to_all(title, body, tag)
            # Sil
            del_req = urllib.request.Request(
                f'{FIREBASE_URL}/gridtracker/pushQueue/{tag}.json',
                method='DELETE')
            urllib.request.urlopen(del_req, timeout=5)
    except Exception as e:
        print(f'[PushQueue] hata: {e}')

# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        path = self.path.split('?')[0]
        # POST /api/notify
        if path == '/api/notify':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body   = self.rfile.read(length)
                data   = json.loads(body.decode('utf-8')) if body else {}
            except Exception:
                data = {}
            title = data.get('title', 'GridTracker')
            body  = data.get('body', '')
            tag   = data.get('tag', 'gridtracker')
            threading.Thread(
                target=send_push_to_all,
                args=(title, body, tag),
                daemon=True
            ).start()
            self.send_json(200, {'ok': True})
            return
        self.send_json(405, {'error': 'Method Not Allowed'})

    def do_GET(self):
        if self.path in ('/', ''):
            self.send_response(302)
            self.send_header('Location', '/bist_tracker.html')
            self.end_headers()
            return

        path  = self.path.split('?')[0]
        parts = path.strip('/').split('/')

        # /api/stock/{SYM}
        if len(parts) == 3 and parts[0] == 'api' and parts[1] == 'stock':
            sym = parts[2].upper()
            with _lock:
                data = _stocks.get(sym)
            if data:
                self.send_json(200, data)
            else:
                self.send_json(404, {'error': f'{sym} bulunamadı'})
            return

        # /api/all
        if path == '/api/all':
            with _lock:
                self.send_json(200, {'stocks': dict(_stocks), 'ts': _stocks_ts})
            return

        # /api/health
        if path == '/api/health':
            with _lock:
                self.send_json(200, {'ok': True, 'count': len(_stocks), 'ts': _stocks_ts})
            return

        # Statik dosyalar
        super().do_GET()

    def translate_path(self, path):
        import posixpath, urllib.parse
        path = posixpath.normpath(urllib.parse.unquote(path.split('?')[0]))
        result = BASE_DIR
        for part in path.split('/'):
            if part in ('', os.curdir, os.pardir): continue
            result = os.path.join(result, part)
        return result

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    os.chdir(BASE_DIR)
    # İlk okuma
    stocks = read_excel()
    with _lock:
        _stocks.update(stocks)
        _stocks_ts = int(time.time())
    print(f'[GridTracker] {len(_stocks)} hisse yüklendi.')
    # Firebase'e yaz (IP + ilk veri)
    ip = get_server_ip()
    threading.Thread(target=firebase_put, daemon=True,
        args=('gridtracker/serverInfo', {'ip': ip, 'port': PORT})).start()
    threading.Thread(target=firebase_put, daemon=True,
        args=('gridtracker/stocks', dict(_stocks))).start()
    # Arka plan döngüsü
    threading.Thread(target=_bg_loop, daemon=True).start()
    # Push queue kontrol döngüsü (10s)
    threading.Thread(target=_push_queue_loop, daemon=True).start()
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f'[GridTracker] http://localhost:{PORT}/bist_tracker.html')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
