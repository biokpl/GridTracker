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
import urllib.request, json, socket, threading, time, os, logging

FIREBASE_URL = 'https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app'
PORT = 5050
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ATR_FILE   = os.path.join(BASE_DIR, 'ATR_Sonuc.xlsx')
DD_FILE    = os.path.join(BASE_DIR, 'Destek_Direc_Seviyeleri.xlsx')
VAPID_FILE = os.path.join(BASE_DIR, 'vapid_keys.json')
LOG_FILE   = os.path.join(BASE_DIR, 'server.log')

VAPID_CLAIMS = {'sub': 'mailto:admin@gridtracker.local'}

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8')]
)
slog = logging.getLogger('server')

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
            slog.warning(f'[ATR] okuma hatası: {e}')

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
            slog.warning(f'[DD] okuma hatası: {e}')

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
        slog.warning(f'[Firebase] hata: {e}')

def firebase_get(path):
    try:
        req = urllib.request.Request(
            f'{FIREBASE_URL}/{path}.json',
            headers={'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode())
    except Exception as e:
        slog.warning(f'[Firebase] GET hata: {e}')
        return None

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
            slog.warning(f'[BG] hata: {e}')
        time.sleep(60)

def _push_queue_loop():
    """Her 10 saniyede bir Firebase pushQueue kontrol et."""
    while True:
        try:
            _check_push_queue()
        except Exception as e:
            slog.warning(f'[PushQueue] hata: {e}')
        time.sleep(10)

# ---------------------------------------------------------------------------
# Push Bildirimleri
# ---------------------------------------------------------------------------

def _load_vapid():
    try:
        with open(VAPID_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        slog.warning(f'[Push] VAPID yüklenemedi: {e}')
        return None

def send_push_to_all(title, body, tag='gridtracker'):
    keys = _load_vapid()
    if not keys:
        slog.warning('[Push] VAPID anahtarı yok, bildirim atlandı.')
        return
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        slog.warning('[Push] pywebpush yüklü değil.')
        return
    try:
        req = urllib.request.Request(
            f'{FIREBASE_URL}/gridtracker/pushSubscriptions.json')
        resp = urllib.request.urlopen(req, timeout=10)
        subs = json.loads(resp.read().decode())
    except Exception as e:
        slog.warning(f'[Push] Aboneler alınamadı: {e}')
        return
    if not subs or not isinstance(subs, dict):
        slog.warning('[Push] Kayıtlı abone yok — telefon uygulamayı kapatmış olabilir, yeniden abone ol.')
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
            slog.info(f'[Push] Gönderildi: {sub_key[:12]}…')
        except WebPushException as e:
            status = getattr(e.response, 'status_code', None) if e.response else None
            if status == 410:
                # Subscription kalıcı olarak silindi (410) — Firebase'den kaldır
                try:
                    del_req = urllib.request.Request(
                        f'{FIREBASE_URL}/gridtracker/pushSubscriptions/{sub_key}.json',
                        method='DELETE')
                    urllib.request.urlopen(del_req, timeout=5)
                    slog.warning(f'[Push] Kalıcı silinen abone kaldırıldı (HTTP 410): {sub_key[:12]}…')
                except Exception:
                    pass
            else:
                slog.warning(f'[Push] WebPush hatası [{sub_key[:12]}…]: {e}')
        except Exception as e:
            slog.warning(f'[Push] Beklenmeyen hata [{sub_key[:12]}…]: {e}')
    slog.info(f'[Push] Tamamlandı: {sent}/{len(subs)} abone başarılı — {title}')

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
        slog.warning(f'[PushQueue] hata: {e}')

# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def end_headers(self):
        # sw.js ve manifest.json asla cache'lenmesin
        path = self.path.split('?')[0]
        if path in ('/sw.js', '/manifest.json'):
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
            self.send_header('Pragma', 'no-cache')
        super().end_headers()

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

        # /api/grid-data — LCD için realNet, openPosCount, todayProfit
        if path == '/api/grid-data':
            bt_file = os.path.join(BASE_DIR, 'bist_tracker.html')
            realNet = 0.0
            openPosCount = 0
            todayProfit = 0.0
            todayOverall = 0.0
            if os.path.exists(bt_file):
                try:
                    with open(bt_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    import re
                    m = re.search(r'"realNet":\s*([-\d.]+)', content)
                    if m: realNet = float(m.group(1))
                    m = re.search(r'"openPosCount":\s*(\d+)', content)
                    if m: openPosCount = int(m.group(1))
                    m = re.search(r'"todayOverall":\s*([-\d.]+)', content)
                    if m: todayOverall = float(m.group(1))
                    m = re.search(r'"netProfit":\s*([-\d.]+)', content)
                    if m: todayProfit = float(m.group(1))
                except Exception as e:
                    slog.warning(f'[GridData] okuma hatası: {e}')
            self.send_json(200, {
                'realNet': realNet,
                'openPosCount': openPosCount,
                'todayProfit': todayProfit,
                'todayOverall': todayOverall
            })
            return

        # /api/all-data — LCD için TÜM VERİ (tek istek, Firebase'e gerek yok)
        if path == '/api/all-data':
            bt_file = os.path.join(BASE_DIR, 'bist_tracker.html')
            data = {
                'today': '', 'todayOverall': 0.0,
                'realNet': 0.0, 'openPosCount': 0,
                'todayNet': 0.0, 'todayGross': 0.0, 'todayComm': 0.0,
                'todayBuys': 0, 'todaySells': 0,
                'totalProfit': 0.0, 'portfolioDiff': 0.0,
                'currentMonthNet': 0.0,
                'botSymbols': [], 'monthlyKar': [], 'openPositions': [],
                'dailyLog': {},
                'posMonitor': {}
            }
            if os.path.exists(bt_file):
                try:
                    with open(bt_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    import re

                    # window.__GRID_DATA__ bloğunu çıkar — non-greedy + DOTALL
                    m = re.search(r'window\.__GRID_DATA__\s*=\s*(\{.*?})\s*;', content, re.DOTALL)
                    if not m:
                        m = re.search(r'window\.__GRID_DATA__\s*=\s*(\{.*)', content)
                    if m:
                        try:
                            json_str = m.group(1)
                            # JavaScript temizleme
                            json_str = re.sub(r'^\s*//.*', '', json_str, flags=re.MULTILINE)
                            json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
                            try:
                                gd = json.loads(json_str)
                            except json.JSONDecodeError as e:
                                # Kırpılmış olabilir — sonunda fazlalık var, tamamlanana kadar kırp
                                depth = 0
                                last_ok = 0
                                for i, c in enumerate(json_str):
                                    if c == '{': depth += 1
                                    elif c == '}':
                                        depth -= 1
                                        if depth == 0:
                                            last_ok = i + 1
                                            break
                                if last_ok > 0:
                                    gd = json.loads(json_str[:last_ok])
                                else:
                                    gd = {}

                            data['today'] = gd.get('today', '')
                            data['todayOverall'] = gd.get('todayOverall', 0.0)

                            # realNet & openPosCount — FIREBASE'DEN ANLIK AL (canlı veri)
                            tp = firebase_get('gridtracker/todayProfit')
                            if tp:
                                total_net = tp.get('totalNet', 0.0)
                                open_pos_all = tp.get('openPositions', {})

                                bot_syms = data.get('botSymbols', [])
                                if not bot_syms:
                                    settings = gd.get('settings', {})
                                    bot_syms = settings.get('botSymbols', [])
                                open_pos = {k: v for k, v in open_pos_all.items() if k in bot_syms}

                                unrealized = 0.0
                                stocks_raw = firebase_get('gridtracker/stocks')
                                if stocks_raw:
                                    for sym, pos_list in open_pos.items():
                                        cur_price = stocks_raw.get(sym, {}).get('price', 0)
                                        if cur_price <= 0: continue
                                        for pos in pos_list:
                                            qty = pos.get('execQty', 0)
                                            px = pos.get('execPrice', 0)
                                            exec_amt = pos.get('execAmount', 0)
                                            comm = pos.get('commission', 0)
                                            comm_rate = exec_amt > 0 and comm / exec_amt or 0.0001
                                            sell_comm = cur_price * qty * comm_rate
                                            unrealized += (cur_price - px) * qty - sell_comm
                                data['realNet'] = total_net + unrealized
                                open_count = sum(len(v) for v in open_pos.values())
                                data['openPosCount'] = open_count

                                # posMonitor — en fazla lotlu botSymbol (LCD 5. sayfa)
                                pos_mon = {'symbol': '', 'qty': 0, 'avgCost': 0.0,
                                           'curPrice': 0.0, 'unrealPnl': 0.0, 'posCount': 0}
                                best_sym, best_qty = '', 0
                                for sym, pl in open_pos.items():
                                    q = sum(p.get('execQty', 0) for p in pl)
                                    if q > best_qty:
                                        best_qty, best_sym = q, sym
                                if best_sym and best_qty > 0:
                                    pl = open_pos[best_sym]
                                    avg_c = sum(p.get('execQty', 0) * p.get('execPrice', 0) for p in pl) / best_qty
                                    c_px = stocks_raw.get(best_sym, {}).get('price', 0) if stocks_raw else 0
                                    cr = 0.0001
                                    if pl and pl[0].get('execAmount', 0) > 0:
                                        cr = pl[0].get('commission', 0) / pl[0].get('execAmount', 1)
                                    u_pnl = (c_px - avg_c) * best_qty - c_px * best_qty * cr if c_px > 0 else 0.0
                                    pos_mon = {'symbol': best_sym, 'qty': best_qty,
                                               'avgCost': round(avg_c, 2), 'curPrice': round(c_px, 2),
                                               'unrealPnl': round(u_pnl, 0), 'posCount': len(pl)}
                                data['posMonitor'] = pos_mon
                            else:
                                data['realNet'] = gd.get('realNet', 0.0)
                                data['openPosCount'] = gd.get('openPosCount', 0)

                            # dailyLog (bugünün net/gross/comm/buys/sells)
                            dl = gd.get('dailyLog', {})
                            today_key = gd.get('today', '')
                            today_dl = dl.get(today_key, {}) if today_key else {}
                            data['todayNet'] = today_dl.get('netProfit', 0.0)
                            data['todayGross'] = today_dl.get('grossProfit', 0.0)
                            data['todayComm'] = today_dl.get('commission', 0.0)
                            data['todayBuys'] = today_dl.get('buys', 0)
                            data['todaySells'] = today_dl.get('sells', 0)

                            # totalProfit & portfolioDiff
                            data['totalProfit'] = gd.get('totalProfit', 0.0)
                            data['portfolioDiff'] = gd.get('portfolioDiff', 0.0)

                            # portfolioDiff — bugünün overall farkı
                            oh = gd.get('overallHistory', [])
                            today_ov = gd.get('todayOverall', 0.0)
                            today_cap_sum = 0.0
                            birikim = gd.get('birikimTx', [])
                            for tx in birikim:
                                d = tx.get('date', '')
                                if d == today_key and not tx.get('exclude', False) and not tx.get('trackPayment', False):
                                    today_cap_sum += tx.get('amount', 0.0)
                            prev_oh = None
                            for h in sorted(oh, key=lambda x: x['date'], reverse=True):
                                if h['date'] < today_key:
                                    prev_oh = h
                                    break
                            if prev_oh:
                                perf_diff = (today_ov - prev_oh.get('amount', 0.0)) - today_cap_sum
                                data['portfolioDiff'] = perf_diff

                            # currentMonthNet — aylık kar (bu ay + geçmiş aylık fark)
                            import datetime
                            now = datetime.datetime.now()
                            cur_year = now.year
                            cur_month = now.month
                            cur_month_key = f'{cur_year}-{cur_month:02d}'
                            month_net = 0.0
                            for dk, dv in dl.items():
                                if dk.startswith(cur_month_key):
                                    month_net += dv.get('netProfit', 0.0)
                            data['currentMonthNet'] = month_net

                            # botSymbols — settings altında
                            settings = gd.get('settings', {})
                            data['botSymbols'] = settings.get('botSymbols', [])

                            # monthlyKar
                            data['monthlyKar'] = gd.get('monthlyKar', [])

                            # monthlyTradesNet — son 3 ayın işlem netleri (dailyLog'dan)
                            import datetime
                            now2 = datetime.datetime.now()
                            cur_year2 = now2.year
                            cur_month2 = now2.month
                            turkish_months = {1:'OCAK',2:'SUBAT',3:'MART',4:'NISAN',5:'MAYIS',6:'HAZIRAN',
                                              7:'TEMMUZ',8:'AGUSTOS',9:'EYLUL',10:'EKIM',11:'KASIM',12:'ARALIK'}
                            # Ayları topla
                            mons_sum = {}
                            for dk in dl.keys():
                                if isinstance(dk, str) and len(dk) >= 7:
                                    ym = dk[:7]
                                    if ym not in mons_sum:
                                        mons_sum[ym] = 0.0
                                    mons_sum[ym] += dl[dk].get('netProfit', 0.0)
                            # Son 3 ayı sırala
                            sorted_mons = sorted(mons_sum.items(), key=lambda x: x[0], reverse=True)
                            monthly_trades_net = []
                            for ym, profit in sorted_mons[:3]:
                                parts = ym.split('-')
                                m = int(parts[1])
                                trname = turkish_months.get(m, ym)
                                monthly_trades_net.append({'key': ym, 'trname': trname, 'profit': int(profit)})
                            data['monthlyTradesNet'] = monthly_trades_net

                            # openPositions
                            data['openPositions'] = gd.get('openPositions', {})

                            # dailyLog (sadece aylık özet — ESP32 tampon sınırı için)
                            data['dailyLog'] = {}

                            slog.info(f'[AllData] today={data["today"]}')
                        except json.JSONDecodeError as e:
                            slog.warning(f'[AllData] JSON parse hatası: {e}')
                except Exception as e:
                    slog.warning(f'[AllData] okuma hatası: {e}')
            self.send_json(200, data)
            return

        # /api/grid-analysis — Grid bot analiz sonucu (ESP32 LCD 3. sayfa)
        if path == '/api/grid-analysis':
            result_file = os.path.join(BASE_DIR, 'grid_analysis_result.json')
            if os.path.exists(result_file):
                try:
                    with open(result_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    self.send_json(200, data)
                except Exception as e:
                    slog.warning(f'[GridAnaliz] okuma hatası: {e}')
                    self.send_json(500, {'error': str(e)})
            else:
                self.send_json(404, {'error': 'Henuz analiz yapilmadi'})
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
    slog.info(f'[GridTracker] {len(_stocks)} hisse yüklendi.')
    # Firebase'e yaz (IP + ilk veri)
    ip = get_server_ip()
    threading.Thread(target=firebase_put, daemon=True,
        args=('gridtracker/serverInfo', {'ip': ip, 'port': PORT})).start()
    threading.Thread(target=firebase_put, daemon=True,
        args=('gridtracker/stocks', dict(_stocks))).start()
    # Arka plan döngüsü
    threading.Thread(target=_bg_loop, daemon=True).start()
    # Push queue → automation_server.pyw (port 5051) tarafından işleniyor
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    slog.info(f'[GridTracker] http://localhost:{PORT}/bist_tracker.html')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
