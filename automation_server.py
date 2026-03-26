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

import sys, os, re, json, subprocess, argparse, configparser
from pathlib import Path
from datetime import date

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
    python = sys.executable
    script = str(SCRIPT_DIR / 'morning_automation.py')

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


# ── Task Scheduler setup ───────────────────────────────────
def setup_autostart():
    """Sunucuyu Windows oturumu açılışında otomatik başlatmak için görev ekler."""
    python = sys.executable
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Otomasyon Ayarlar Sunucusu')
    parser.add_argument('--setup', action='store_true',
                        help='Windows oturumunda otomatik başlatmak için görev ekle')
    args = parser.parse_args()

    if args.setup:
        setup_autostart()
    else:
        print(f'Otomasyon ayarlar sunucusu başlatılıyor: http://localhost:{PORT}')
        app.run(host='127.0.0.1', port=PORT, debug=False)
