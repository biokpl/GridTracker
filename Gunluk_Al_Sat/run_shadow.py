"""
run_shadow.py — GÖLGE MOD başlatıcı (Raspberry Pi paralel testi, 2026-10-25).

Bir betiği (monitor.pyw / advisor.py) OLDUĞU GİBİ çalıştırır ama dışarıya YAZMAZ:
  • requests.put/patch/post/delete → gerçek istek yapılmaz, shadow_writes.log'a kaydedilir
    (Firebase güncellemesi, ntfy bildirimi, kalp atışı... hepsi sadece günlüğe düşer)
  • okuma (GET, Yahoo, Firebase okuma) normal çalışır
Yerel dosyalar (state.json, advisor_result.json, monitor.log) bu kopyanın kendi klasöründe kalır.

Kullanım: python run_shadow.py monitor.pyw
          python run_shadow.py advisor.py --run
"""
import os, sys, runpy, json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
LOG = HERE / "shadow_writes.log"
os.environ["GT_SHADOW"] = "1"

import requests


class _FakeResp:
    status_code = 200
    ok = True
    text = "{}"
    content = b"{}"
    def json(self): return {}
    def raise_for_status(self): pass


def _fake(method):
    def f(url, *a, **k):
        body = k.get("json") if k.get("json") is not None else k.get("data")
        try:
            body = json.dumps(body, ensure_ascii=False, default=str) if not isinstance(body, (str, bytes)) else body
        except Exception:
            body = str(body)
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        title = (k.get("headers") or {}).get("Title") or ""
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {method} {url.split('?')[0]} {title} {str(body)[:300]}\n")
        return _FakeResp()
    return f


for _m in ("put", "patch", "post", "delete"):
    setattr(requests, _m, _fake(_m.upper()))

if __name__ == "__main__":
    target = HERE / sys.argv[1]
    sys.argv = [str(target)] + sys.argv[2:]
    sys.path.insert(0, str(HERE))
    os.chdir(HERE)
    runpy.run_path(str(target), run_name="__main__")
