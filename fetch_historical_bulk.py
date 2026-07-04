"""
STEP 3 — Bulk historical fetch for your company list.

Reads your company list, resolves each Symbol to a Kite instrument_token,
then downloads ~8 years of daily candles (price + volume) per company,
saving one CSV per company plus a summary report and a live snapshot.

SETUP (one time):
  1. pip install pandas   (kiteconnect already installed)
  2. Export your Excel sheet as CSV:  File -> Save As -> CSV
     Name it  companies.csv  and put it in this folder.
     (Tab-separated .txt also works — the script auto-detects.)
     It must contain the column:  Symbol
  3. Make sure kite_session.json exists (run generate_token.py today).

RUN:
  python fetch_historical_bulk.py

OUTPUT:
  data/<SYMBOL>.csv     one file per company: date,open,high,low,close,volume
  summary.csv           per-symbol status: rows fetched, first/last date
  snapshot.csv          current price, volume, % change for all symbols
  missing_symbols.txt   symbols that could not be resolved on NSE

RESUME: already-downloaded symbols (existing CSV in data/) are skipped,
so you can safely re-run after any interruption.
"""

import csv
import json
import os
import sys
import time
import datetime

import pandas as pd
from kiteconnect import KiteConnect

SESSION_FILE = "kite_session.json"
COMPANIES_FILE = "companies.csv"
DATA_DIR = "data"

YEARS_BACK = 8
INTERVAL = "day"
SLEEP_BETWEEN_CALLS = 0.35   # ~3 req/sec limit on historical API


def load_symbols():
    """Read the Symbol column from companies.csv (comma or tab separated)."""
    if not os.path.exists(COMPANIES_FILE):
        sys.exit(
            f"{COMPANIES_FILE} not found. Export your Excel sheet as CSV "
            "into this folder first."
        )
    with open(COMPANIES_FILE, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
        reader = csv.DictReader(f, delimiter=delimiter)
        cols = {c.strip().lower(): c for c in reader.fieldnames}
        if "symbol" not in cols:
            sys.exit(f"No 'Symbol' column found. Columns seen: {reader.fieldnames}")
        sym_col = cols["symbol"]
        isin_col = cols.get("isin code")
        symbols = []
        for row in reader:
            sym = (row.get(sym_col) or "").strip()
            isin = (row.get(isin_col) or "").strip() if isin_col else ""
            if not sym:
                continue
            if sym.startswith("DUMMY") or isin.startswith("DUM"):
                continue  # placeholder rows from corporate actions
            symbols.append(sym)
    # de-duplicate, preserve order
    seen = set()
    return [s for s in symbols if not (s in seen or seen.add(s))]


def year_chunks(start: datetime.date, end: datetime.date):
    """Yield (from, to) pairs, one per calendar year slice."""
    cur = start
    while cur <= end:
        chunk_end = min(datetime.date(cur.year, 12, 31), end)
        yield cur, chunk_end
        cur = chunk_end + datetime.timedelta(days=1)


def main():
    try:
        with open(SESSION_FILE) as f:
            session = json.load(f)
    except FileNotFoundError:
        sys.exit("kite_session.json not found. Run generate_token.py first.")

    kite = KiteConnect(api_key=session["api_key"])
    kite.set_access_token(session["access_token"])

    try:
        kite.profile()
    except Exception as e:
        sys.exit(f"Token expired ({e}). Re-run generate_token.py.")

    symbols = load_symbols()
    print(f"Loaded {len(symbols)} symbols from {COMPANIES_FILE}")

    print("Downloading NSE instrument master...")
    instruments = kite.instruments("NSE")
    token_map = {row["tradingsymbol"]: row["instrument_token"] for row in instruments}

    os.makedirs(DATA_DIR, exist_ok=True)
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=YEARS_BACK * 365)

    missing, summary = [], []
    total = len(symbols)

    for i, sym in enumerate(symbols, 1):
        out_path = os.path.join(DATA_DIR, f"{sym}.csv")
        if os.path.exists(out_path):
            print(f"[{i}/{total}] {sym}: already downloaded, skipping")
            continue

        token = token_map.get(sym)
        if token is None:
            print(f"[{i}/{total}] {sym}: NOT FOUND on NSE — logged")
            missing.append(sym)
            continue

        all_candles = []
        try:
            for frm, to in year_chunks(start_date, end_date):
                candles = kite.historical_data(
                    instrument_token=token,
                    from_date=frm,
                    to_date=to,
                    interval=INTERVAL,
                )
                all_candles.extend(candles)
                time.sleep(SLEEP_BETWEEN_CALLS)
        except Exception as e:
            print(f"[{i}/{total}] {sym}: ERROR {e} — will retry on next run")
            time.sleep(2)
            continue

        if not all_candles:
            print(f"[{i}/{total}] {sym}: no data returned")
            summary.append({"symbol": sym, "rows": 0})
            continue

        df = pd.DataFrame(all_candles)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df[["date", "open", "high", "low", "close", "volume"]]
        df.to_csv(out_path, index=False)

        summary.append(
            {
                "symbol": sym,
                "rows": len(df),
                "first_date": df["date"].iloc[0],
                "last_date": df["date"].iloc[-1],
            }
        )
        print(f"[{i}/{total}] {sym}: {len(df)} days "
              f"({df['date'].iloc[0]} to {df['date'].iloc[-1]})")

    if summary:
        pd.DataFrame(summary).to_csv("summary.csv", index=False)
    if missing:
        with open("missing_symbols.txt", "w") as f:
            f.write("\n".join(missing))
        print(f"\n{len(missing)} unresolved symbols written to missing_symbols.txt")

    # ---- Live snapshot: fill price / volume / % change for the whole list
    print("\nFetching current snapshot (price, volume, % change)...")
    rows = []
    resolved = [s for s in symbols if s in token_map]
    for j in range(0, len(resolved), 400):  # quote allows up to 500 per call
        batch = [f"NSE:{s}" for s in resolved[j : j + 400]]
        try:
            quotes = kite.quote(batch)
        except Exception as e:
            print("Snapshot batch failed:", e)
            continue
        for key, q in quotes.items():
            prev_close = q.get("ohlc", {}).get("close") or 0
            ltp = q.get("last_price") or 0
            pct = round((ltp - prev_close) / prev_close * 100, 2) if prev_close else None
            rows.append(
                {
                    "symbol": key.split(":", 1)[1],
                    "price": ltp,
                    "volume": q.get("volume"),
                    "percent_change": pct,
                }
            )
        time.sleep(0.5)
    if rows:
        pd.DataFrame(rows).to_csv("snapshot.csv", index=False)
        print(f"snapshot.csv written with {len(rows)} symbols")

    print("\nDone. Historical CSVs are in the data/ folder.")


if __name__ == "__main__":
    main()