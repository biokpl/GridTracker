#!/usr/bin/env python3
"""
GridTracker Server - port 5050
- GET /               → bist_tracker.html servis eder
- GET /api/atr/{SYM}  → Yahoo Finance fiyat
- GET /api/sr/{SYM}   → Destek/Direnç
Stdlib only, pip gerekmez.
"""
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.request, json, socket, threading, time, os, sys

FIREBASE_URL = 'https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app'
PORT = 5050
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_server_ip():
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ip.startswith('100.'):   # Tailscale tercihli
                return ip
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

def firebase_put(path, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f'{FIREBASE_URL}/{path}.json', data=body, method='PUT',
            headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

def yahoo_fetch(ticker, range_='5d', interval='1d'):
    url = (f'https://query2.finance.yahoo.com/v8/finance/chart/'
           f'{ticker}?interval={interval}&range={range_}')
    req = urllib.request.Request(url, headers={
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 Chrome/124.0 Safari/537.36'),
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read())

def extract_price(data):
    r = data['chart']['result'][0]
    price = r['meta'].get('regularMarketPrice')
    if price is None:
        closes = [v for v in r['indicators']['quote'][0].get('close', []) if v is not None]
        price = closes[-1]
    return round(float(price), 2)

def calc_sr(data, mode):
    q = data['chart']['result'][0]['indicators']['quote'][0]
    prices = [(h, l, c) for h, l, c in zip(
                  q.get('high', []), q.get('low', []), q.get('close', []))
              if h is not None and l is not None and c is not None]
    if not prices:
        raise ValueError('Veri yok')
    current = prices[-1][2]
    if mode == 'main':
        return {'support': round(min(p[1] for p in prices), 2),
                'resistance': round(max(p[0] for p in prices), 2)}
    W, n, sh, sl = 2, len(prices), [], []
    for i in range(W, n - W):
        h, l = prices[i][0], prices[i][1]
        if all(h >= prices[i - W + j][0] for j in range(W * 2) if j != W): sh.append(h)
        if all(l <= prices[i - W + j][1] for j in range(W * 2) if j != W): sl.append(l)
    idx  = 4 if mode == 'swing5' else 2 if mode == 'swing3' else 0
    sups = sorted([p for p in sl if p < current * 0.998], reverse=True)
    ress = sorted([p for p in sh if p > current * 1.002])
    return {
        'support':    round((sups[idx] if idx < len(sups) else (sups[-1] if sups else min(p[1] for p in prices))), 2),
        'resistance': round((ress[idx] if idx < len(ress) else (ress[-1] if ress else max(p[0] for p in prices))), 2),
    }

# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class Handler(SimpleHTTPRequestHandler):
    """API route'ları yakalar, geri kalan her şeyi BASE_DIR'den servis eder."""

    def log_message(self, fmt, *args):
        pass

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.end_headers()

    def do_GET(self):
        # Kök URL → doğrudan HTML'e yönlendir
        if self.path in ('/', ''):
            self.send_response(302)
            self.send_header('Location', '/bist_tracker.html')
            self.end_headers()
            return

        path  = self.path.split('?')[0]
        parts = path.strip('/').split('/')

        # /api/atr/{SYM}
        if len(parts) == 3 and parts[0] == 'api' and parts[1] == 'atr':
            sym = parts[2].upper()
            try:
                price = extract_price(yahoo_fetch(sym + '.IS', '5d'))
                threading.Thread(target=firebase_put, daemon=True,
                    args=(f'gridtracker/livePrices/{sym}',
                          {'price': price, 'ts': int(time.time())})).start()
                self.send_json(200, {'price': price})
            except Exception as e:
                self.send_json(500, {'error': str(e)})
            return

        # /api/sr/{SYM}?mode=...
        if len(parts) == 3 and parts[0] == 'api' and parts[1] == 'sr':
            sym  = parts[2].upper()
            qs   = self.path.split('?')[1] if '?' in self.path else ''
            mode = next((v.split('=')[1] for v in qs.split('&') if v.startswith('mode=')), 'main')
            try:
                sr = calc_sr(yahoo_fetch(sym + '.IS', '60d'), mode)
                threading.Thread(target=firebase_put, daemon=True,
                    args=(f'gridtracker/srCache/{sym}_{mode}', sr)).start()
                self.send_json(200, sr)
            except Exception as e:
                self.send_json(500, {'error': str(e)})
            return

        # /api/health
        if path == '/api/health':
            self.send_json(200, {'ok': True})
            return

        # Statik dosya (bist_tracker.html, sw.js, ikonlar vs.)
        super().do_GET()

    def translate_path(self, path):
        # SimpleHTTPRequestHandler'ı BASE_DIR'e kilitle
        import posixpath, urllib.parse
        path = posixpath.normpath(urllib.parse.unquote(path.split('?')[0]))
        parts = path.split('/')
        path  = BASE_DIR
        for part in parts:
            if part in ('', os.curdir, os.pardir):
                continue
            path = os.path.join(path, part)
        return path

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def register():
    ip = get_server_ip()
    firebase_put('gridtracker/serverInfo', {'ip': ip, 'port': PORT})

if __name__ == '__main__':
    os.chdir(BASE_DIR)
    threading.Thread(target=register, daemon=True).start()
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f'GridTracker Server: http://localhost:{PORT}/bist_tracker.html')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
