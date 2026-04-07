#!/usr/bin/env python3
"""
GridTracker Price Server - port 5050
Yahoo Finance proxy for bist_tracker.html (stdlib only, no pip needed)
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request, json, socket, threading, time

FIREBASE_URL = 'https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app'
PORT = 5050

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_server_ip():
    """Tailscale IP (100.x.x.x) tercihli, yoksa LAN IP."""
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ip.startswith('100.'):
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
        url = f'{FIREBASE_URL}/{path}.json'
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, method='PUT',
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
    highs  = q.get('high', [])
    lows   = q.get('low', [])
    closes = q.get('close', [])
    prices = [(h, l, c) for h, l, c in zip(highs, lows, closes)
              if h is not None and l is not None and c is not None]
    if not prices:
        raise ValueError('Veri yok')
    current = prices[-1][2]
    if mode == 'main':
        support    = round(min(p[1] for p in prices), 2)
        resistance = round(max(p[0] for p in prices), 2)
        return {'support': support, 'resistance': resistance}
    W = 2
    n = len(prices)
    sh, sl = [], []
    for i in range(W, n - W):
        h, l = prices[i][0], prices[i][1]
        if all(h >= prices[i - W + j][0] for j in range(W * 2) if j != W):
            sh.append(h)
        if all(l <= prices[i - W + j][1] for j in range(W * 2) if j != W):
            sl.append(l)
    idx = 4 if mode == 'swing5' else 2 if mode == 'swing3' else 0
    sups = sorted([p for p in sl if p < current * 0.998], reverse=True)
    ress = sorted([p for p in sh if p > current * 1.002])
    support    = round((sups[idx] if idx < len(sups) else
                        (sups[-1] if sups else min(p[1] for p in prices))), 2)
    resistance = round((ress[idx] if idx < len(ress) else
                        (ress[-1] if ress else max(p[0] for p in prices))), 2)
    return {'support': support, 'resistance': resistance}

# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # sessiz log

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
        path = self.path.split('?')[0]
        parts = path.strip('/').split('/')

        # /api/atr/{SYM}  →  fiyat
        if len(parts) == 3 and parts[0] == 'api' and parts[1] == 'atr':
            sym = parts[2].upper()
            try:
                data  = yahoo_fetch(sym + '.IS', range_='5d')
                price = extract_price(data)
                threading.Thread(
                    target=firebase_put,
                    args=(f'gridtracker/livePrices/{sym}',
                          {'price': price, 'ts': int(time.time())}),
                    daemon=True
                ).start()
                self.send_json(200, {'price': price})
            except Exception as e:
                self.send_json(500, {'error': str(e)})
            return

        # /api/sr/{SYM}?mode={mode}  →  destek/direnç
        if len(parts) == 3 and parts[0] == 'api' and parts[1] == 'sr':
            sym  = parts[2].upper()
            qs   = self.path.split('?')[1] if '?' in self.path else ''
            mode = next((v.split('=')[1] for v in qs.split('&')
                         if v.startswith('mode=')), 'main')
            try:
                data = yahoo_fetch(sym + '.IS', range_='60d')
                sr   = calc_sr(data, mode)
                threading.Thread(
                    target=firebase_put,
                    args=(f'gridtracker/srCache/{sym}_{mode}', sr),
                    daemon=True
                ).start()
                self.send_json(200, sr)
            except Exception as e:
                self.send_json(500, {'error': str(e)})
            return

        self.send_response(404)
        self.end_headers()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def register():
    ip = get_server_ip()
    firebase_put('gridtracker/serverInfo', {'ip': ip, 'port': PORT})
    print(f'[GridTracker] sunucu IP Firebase\'e yazıldı: {ip}:{PORT}')

if __name__ == '__main__':
    threading.Thread(target=register, daemon=True).start()
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f'[GridTracker] Price Server çalışıyor → http://0.0.0.0:{PORT}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
