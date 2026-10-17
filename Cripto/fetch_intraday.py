"""fetch_intraday.py — Binance açık verisinden (anahtarsız) saatlik/15dk mumlar."""
import sys, time, requests
from pathlib import Path
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = Path(__file__).parent
URL = "https://data-api.binance.vision/api/v3/klines"
COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"]
JOBS = {"1h": "2020-01-01", "15m": "2022-01-01"}


def fetch(sym, interval, start):
    t0 = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    rows = []
    while True:
        for attempt in range(5):
            try:
                r = requests.get(URL, params={"symbol": sym, "interval": interval,
                                              "startTime": t0, "limit": 1000}, timeout=20)
                r.raise_for_status(); k = r.json(); break
            except Exception:
                time.sleep(2 + attempt * 2)
        else:
            raise RuntimeError(f"{sym} {interval} indirilemedi")
        if not k:
            break
        rows += k
        t0 = k[-1][0] + 1
        if len(k) < 1000:
            break
        time.sleep(0.05)
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tb", "tq", "x"])
    df.index = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df[["o", "h", "l", "c", "v"]].astype(float)


if __name__ == "__main__":
    for iv, start in JOBS.items():
        out = {}
        for c in COINS:
            out[c] = fetch(f"{c}USDT", iv, start)
            print(f"{iv} {c}: {len(out[c]):,} mum  {out[c].index[0].date()} → {out[c].index[-1].date()}")
        pd.to_pickle(out, BASE / f"intraday_{iv}.pkl")
