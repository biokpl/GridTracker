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

FIREBASE_URL = 'https://grid-tracker-73ed2-default-rtdb.europe-west1.firebasedatabase.app'

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

for _pkg in ['flask', 'holidays']:
    try:
        __import__(_pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg])

from flask import Flask, request, jsonify, Response

SCRIPT_DIR  = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / 'morning_config.ini'
TASK_NAME   = 'MatriksIQ_Sabah_Otomasyonu'
PORT        = 5050

app = Flask(__name__)


def _cors(resp):
    resp.headers['Access-Control-Allow-Origin']  = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    return resp


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


# ── OPTIONS (preflight) ────────────────────────────────────
@app.route('/api/morning-settings', methods=['OPTIONS'])
def options_settings():
    return _cors(Response('', 204))


# ── GET /api/morning-settings ─────────────────────────────
@app.route('/api/morning-settings', methods=['GET'])
def get_settings():
    cfg = _read_cfg()
    time_str = cfg.get('schedule', 'time', fallback='09:15')
    return _cors(jsonify({
        'time': time_str,
        'wake_time': _wake_time(time_str),
        'task_name': TASK_NAME,
    }))


# ── POST /api/morning-settings ────────────────────────────
@app.route('/api/morning-settings', methods=['POST'])
def save_settings():
    data = request.get_json(force=True)
    time_str = (data or {}).get('time', '').strip()

    if not re.match(r'^\d{2}:\d{2}$', time_str):
        return _cors(jsonify({'error': 'Geçersiz saat formatı (HH:MM bekleniyor)'})), 400

    h, m = map(int, time_str.split(':'))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return _cors(jsonify({'error': 'Saat değeri geçersiz'})), 400

    # Config güncelle
    cfg = _read_cfg()
    if 'schedule' not in cfg:
        cfg.add_section('schedule')
    cfg.set('schedule', 'time', time_str)
    _write_cfg(cfg)

    # Task Scheduler güncelle
    ok, msg = _update_task(time_str)
    wake = _wake_time(time_str)

    return _cors(jsonify({
        'success': True,
        'time': time_str,
        'wake_time': wake,
        'task_ok': ok,
        'task_msg': msg.strip(),
    }))


# ── GET /api/holidays/<year> ───────────────────────────────
@app.route('/api/holidays/<int:year>', methods=['GET'])
def get_holidays(year):
    import holidays as _hol
    tr = _hol.Turkey(years=year)
    items = sorted([{'date': str(d), 'name': name} for d, name in tr.items()],
                   key=lambda x: x['date'])
    return _cors(jsonify(items))


# ── GET /api/atr/<symbol> ─────────────────────────────────
@app.route('/api/atr/<symbol>', methods=['GET', 'OPTIONS'])
def get_atr(symbol):
    if request.method == 'OPTIONS':
        return _cors(Response('', 204))
    try:
        import urllib.request as ur, json as _json
        ticker = symbol.upper() + '.IS'
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=10d'
        req = ur.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with ur.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read())
        result = data['chart']['result'][0]
        quote  = result['indicators']['quote'][0]
        highs  = [v for v in quote['high']  if v is not None][-7:]
        lows   = [v for v in quote['low']   if v is not None][-7:]
        closes = [v for v in quote['close'] if v is not None]
        n = min(len(highs), len(lows))
        if n < 1:
            return _cors(jsonify({'error': 'Yetersiz veri'})), 400
        atr = sum(highs[i] - lows[i] for i in range(n)) / n
        price = closes[-1] if closes else None
        return _cors(jsonify({'atr': round(atr, 4), 'price': round(price, 4) if price else None, 'days': n}))
    except Exception as e:
        return _cors(jsonify({'error': str(e)})), 500


# ── Task Scheduler setup ───────────────────────────────────
def setup_autostart():
    """Sunucuyu Windows oturumu açılışında otomatik başlatmak için görev ekler."""
    python = str(Path(sys.executable).parent / 'pythonw.exe')
    script = str(Path(__file__).resolve())
    cmd = (
        f'schtasks /Create /TN "MatriksIQ_AyarlarSunucusu" '
        f'/TR "\\"{python}\\" \\"{script}\\"" '
        f'/SC ONLOGON /F'
    )
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode == 0:
        print('Sunucu otomatik başlatma görevi eklendi.')
    else:
        print(f'Hata: {result.stdout}{result.stderr}')


def firebase_watcher():
    """
    Firebase'deki /settings/schedule_time değerini 60 saniyede bir izler.
    Değişirse yerel config + Task Scheduler güncellenir.
    """
    last = None
    while True:
        try:
            req = urllib.request.urlopen(
                f'{FIREBASE_URL}/settings/schedule_time.json', timeout=10)
            val = json.loads(req.read().decode())
            if val and isinstance(val, str) and re.match(r'^\d{2}:\d{2}$', val) and val != last:
                cfg = _read_cfg()
                current = cfg.get('schedule', 'time', fallback='09:15')
                if val != current:
                    if 'schedule' not in cfg:
                        cfg.add_section('schedule')
                    cfg.set('schedule', 'time', val)
                    _write_cfg(cfg)
                    ok, _ = _update_task(val)
                    print(f'[Firebase] Saat güncellendi: {val}  (görev: {"OK" if ok else "HATA"})')
                last = val
        except Exception as e:
            pass
        time.sleep(60)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Otomasyon Ayarlar Sunucusu')
    parser.add_argument('--setup', action='store_true',
                        help='Windows oturumunda otomatik başlatmak için görev ekle')
    args = parser.parse_args()

    if args.setup:
        setup_autostart()
    else:
        # Firebase izleyiciyi arka planda başlat
        t = threading.Thread(target=firebase_watcher, daemon=True)
        t.start()
        print(f'Otomasyon ayarlar sunucusu başlatılıyor: http://localhost:{PORT}')
        print(f'Firebase izleyici aktif (60s aralık)')
        app.run(host='127.0.0.1', port=PORT, debug=False)
