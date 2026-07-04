"""
STEP 2 — Run after generate_token.py has created kite_session.json.

Calls all six read-only Kite Connect APIs in sequence and prints the
raw output of each, so you can see exactly what every endpoint returns:

  1. Instruments   GET /instruments          (master list, ~90k rows)
  2. Quote         GET /quote                (full snapshot + depth)
  3. OHLC          GET /quote/ohlc           (open/high/low/last)
  4. LTP           GET /quote/ltp            (last price only)
  5. Historical    GET /instruments/historical/<token>/<interval>
                   (requires the paid historical add-on; handled
                   gracefully if not subscribed)
  6. WebSocket     wss:// live ticks         (runs for ~15 seconds,
                   prints incoming ticks, then disconnects)

Edit SYMBOLS below to test any instruments you like.
Note: outside NSE market hours (09:15-15:30 IST, Mon-Fri) the REST
quotes still return the last known values, but the WebSocket will be
silent — no ticks arrive when the market is closed.
"""

import json
import sys
import datetime
from kiteconnect import KiteConnect, KiteTicker

SESSION_FILE = "kite_session.json"

# Instruments to test with (exchange:tradingsymbol format)
SYMBOLS = ["NSE:INFY", "NSE:RELIANCE", "NSE:NIFTY 50"]

# Symbol whose history and live ticks we inspect
HIST_SYMBOL = "NSE:INFY"

SEP = "\n" + "=" * 70


def pretty(obj, limit=None):
    text = json.dumps(obj, indent=2, default=str)
    if limit and len(text) > limit:
        text = text[:limit] + "\n... (truncated)"
    print(text)


def main():
    try:
        with open(SESSION_FILE) as f:
            session = json.load(f)
    except FileNotFoundError:
        sys.exit("kite_session.json not found. Run generate_token.py first.")

    kite = KiteConnect(api_key=session["api_key"])
    kite.set_access_token(session["access_token"])

    # Sanity check the token before doing anything else
    try:
        profile = kite.profile()
    except Exception as e:
        sys.exit(
            f"Token check failed ({e}). The access token has likely "
            "expired — re-run generate_token.py."
        )
    print(SEP)
    print("Logged in as:", profile.get("user_name"), f"({profile.get('user_id')})")

    # ---------------------------------------------------------- 1
    print(SEP)
    print("1. INSTRUMENTS — GET /instruments (showing first 5 of NSE)")
    print(SEP)
    instruments = kite.instruments("NSE")
    print(f"Total NSE instruments returned: {len(instruments)}")
    pretty(instruments[:5])

    # Build a lookup so we can find the instrument_token for historical/WS
    lookup = {
        f"NSE:{row['tradingsymbol']}": row["instrument_token"]
        for row in instruments
    }
    hist_token = lookup.get(HIST_SYMBOL)
    print(f"\ninstrument_token for {HIST_SYMBOL}: {hist_token}")

    # ---------------------------------------------------------- 2
    print(SEP)
    print(f"2. QUOTE — GET /quote for {SYMBOLS}")
    print(SEP)
    pretty(kite.quote(SYMBOLS))

    # ---------------------------------------------------------- 3
    print(SEP)
    print(f"3. OHLC — GET /quote/ohlc for {SYMBOLS}")
    print(SEP)
    pretty(kite.ohlc(SYMBOLS))

    # ---------------------------------------------------------- 4
    print(SEP)
    print(f"4. LTP — GET /quote/ltp for {SYMBOLS}")
    print(SEP)
    pretty(kite.ltp(SYMBOLS))

    # ---------------------------------------------------------- 5
    print(SEP)
    print(f"5. HISTORICAL — last 5 trading days of {HIST_SYMBOL}, day candles")
    print(SEP)
    try:
        to_date = datetime.date.today()
        from_date = to_date - datetime.timedelta(days=7)
        candles = kite.historical_data(
            instrument_token=hist_token,
            from_date=from_date,
            to_date=to_date,
            interval="day",
        )
        pretty(candles)
    except Exception as e:
        print(
            "Historical call failed:", e,
            "\n(This endpoint needs the paid historical-data add-on "
            "on your Kite Connect app. Everything else still works.)",
        )

    # ---------------------------------------------------------- 6
    print(SEP)
    print(f"6. WEBSOCKET — live ticks for {HIST_SYMBOL} (~15 seconds)")
    print(SEP)

    kws = KiteTicker(session["api_key"], session["access_token"])
    tick_count = {"n": 0}

    def on_ticks(ws, ticks):
        tick_count["n"] += len(ticks)
        pretty(ticks)
        if tick_count["n"] >= 10:  # stop after 10 ticks
            ws.close()

    def on_connect(ws, response):
        print("WebSocket connected. Subscribing (FULL mode)...")
        ws.subscribe([hist_token])
        ws.set_mode(ws.MODE_FULL, [hist_token])

    def on_close(ws, code, reason):
        ws.stop()

    def on_error(ws, code, reason):
        print("WebSocket error:", code, reason)

    kws.on_ticks = on_ticks
    kws.on_connect = on_connect
    kws.on_close = on_close
    kws.on_error = on_error

    import threading

    def stop_later():
        import time
        time.sleep(15)
        try:
            kws.close()
        except Exception:
            pass

    threading.Thread(target=stop_later, daemon=True).start()

    try:
        kws.connect()  # blocking; returns when closed
    except Exception as e:
        print("WebSocket run ended:", e)

    if tick_count["n"] == 0:
        print(
            "No ticks received. If the market is closed "
            "(outside 09:15-15:30 IST, Mon-Fri) this is expected."
        )

    print(SEP)
    print("Done. All six endpoints exercised.")


if __name__ == "__main__":
    main()

  