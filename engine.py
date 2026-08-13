"""
BACKTEST ENGINE — corrected port of backtest.js

Fixes vs the JS version:
  1. Signal on bar t, FILL AT BAR t+1 OPEN  (removes lookahead bias)
  2. Trading costs deducted on both legs
  3. Open positions are force-closed at the end of data (no vanishing trades)
  4. Sizing is explicit and consistent (fixed notional per trade, stated)
  5. Reports avg win / avg loss / profit factor / expectancy
  6. Optional liquidity filter on traded value

Still TODO (Stage 4):
  - Shared capital across symbols (this is still 1 sim per symbol)
  - Equity curve -> drawdown, Sharpe
  - Survivorship: only currently-listed symbols are in the DB
  - Corporate action adjustment
"""

import pandas as pd
from sqlalchemy import create_engine, text

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
PASSWORD = "Aditi1804!!"          # <-- your Postgres password
DB = f"postgresql+psycopg2://postgres:{PASSWORD}@localhost:5432/backtest"

SMA_PERIOD    = 20
CAPITAL       = 100_000            # notional deployed per trade
COST_BPS      = 15                 # per side: STT + exchange + stamp + GST + slippage
MIN_TURNOVER  = 1_000_000          # skip bars with traded value below this (rupees)
MIN_BARS      = 250                # skip symbols with less than ~1 year of history

engine = create_engine(DB)


# ----------------------------------------------------------------------
# DATA
# ----------------------------------------------------------------------
def get_bars(symbol):
    sql = text("""
        SELECT d, open, high, low, close, volume
        FROM bar_daily
        WHERE symbol = :s
        ORDER BY d
    """)
    df = pd.read_sql(sql, engine, params={"s": symbol})
    for c in ["open", "high", "low", "close"]:
        df[c] = df[c].astype(float)
    df["volume"] = df["volume"].astype(float)
    return df


def list_symbols():
    return pd.read_sql(
        "SELECT DISTINCT symbol FROM bar_daily ORDER BY symbol", engine
    )["symbol"].tolist()


# ----------------------------------------------------------------------
# BACKTEST — one symbol
# ----------------------------------------------------------------------
def run_backtest(df, sma_period=SMA_PERIOD, capital=CAPITAL, cost_bps=COST_BPS):
    if len(df) < max(MIN_BARS, sma_period + 2):
        return []

    df = df.copy().reset_index(drop=True)
    df["sma"] = df["close"].rolling(sma_period).mean()
    df["turnover"] = df["close"] * df["volume"]

    trades = []
    in_position = False
    entry_price = entry_date = None
    shares = 0
    pending = None          # signal raised yesterday, fill today at open

    for i in range(1, len(df)):
        prev, curr = df.iloc[i - 1], df.iloc[i]

        # ---- 1. EXECUTE any pending order at TODAY'S OPEN ----
        if pending == "BUY" and not in_position:
            entry_price = curr["open"]
            entry_date  = curr["d"]
            shares      = int(capital // entry_price)
            in_position = shares > 0

        elif pending == "SELL" and in_position:
            exit_price = curr["open"]
            gross = shares * (exit_price - entry_price)
            cost  = shares * (entry_price + exit_price) * cost_bps / 10_000
            trades.append({
                "entry_date": entry_date, "entry_price": entry_price,
                "exit_date": curr["d"],   "exit_price": exit_price,
                "shares": shares, "gross": gross,
                "cost": cost,     "pnl": gross - cost,
            })
            in_position = False
            entry_price = entry_date = None
            shares = 0

        pending = None

        # ---- 2. GENERATE tomorrow's order from TODAY'S CLOSE ----
        if pd.isna(curr["sma"]) or pd.isna(prev["sma"]):
            continue
        if curr["turnover"] < MIN_TURNOVER:
            continue

        crossed_above = prev["close"] <= prev["sma"] and curr["close"] > curr["sma"]
        crossed_below = prev["close"] >= prev["sma"] and curr["close"] < curr["sma"]

        if not in_position and crossed_above:
            pending = "BUY"
        elif in_position and crossed_below:
            pending = "SELL"

    # ---- 3. FORCE-CLOSE anything still open at the last close ----
    if in_position:
        last = df.iloc[-1]
        exit_price = last["close"]
        gross = shares * (exit_price - entry_price)
        cost  = shares * (entry_price + exit_price) * cost_bps / 10_000
        trades.append({
            "entry_date": entry_date, "entry_price": entry_price,
            "exit_date": last["d"],   "exit_price": exit_price,
            "shares": shares, "gross": gross,
            "cost": cost,     "pnl": gross - cost,
            "forced_close": True,
        })

    return trades


# ----------------------------------------------------------------------
# REPORTING
# ----------------------------------------------------------------------
def summarise(trades, label=""):
    if not trades:
        return None
    t = pd.DataFrame(trades)
    wins, losses = t[t.pnl > 0], t[t.pnl <= 0]
    gross_win  = wins.pnl.sum()
    gross_loss = abs(losses.pnl.sum())
    return {
        "label": label,
        "trades": len(t),
        "win_rate": len(wins) / len(t) * 100,
        "avg_win": wins.pnl.mean() if len(wins) else 0.0,
        "avg_loss": losses.pnl.mean() if len(losses) else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss else float("inf"),
        "expectancy": t.pnl.mean(),
        "gross_pnl": t.gross.sum(),
        "costs": t.cost.sum(),
        "net_pnl": t.pnl.sum(),
    }


def print_summary(s):
    if s is None:
        print("no trades")
        return
    print(f"\n=== {s['label']} ===")
    print(f"  trades         {s['trades']:>12,}")
    print(f"  win rate       {s['win_rate']:>11.1f}%")
    print(f"  avg win        {s['avg_win']:>12,.0f}")
    print(f"  avg loss       {s['avg_loss']:>12,.0f}")
    print(f"  profit factor  {s['profit_factor']:>12.2f}")
    print(f"  expectancy     {s['expectancy']:>12,.0f}   <- per trade, after costs")
    print(f"  gross pnl      {s['gross_pnl']:>12,.0f}")
    print(f"  costs          {s['costs']:>12,.0f}")
    print(f"  NET pnl        {s['net_pnl']:>12,.0f}")


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
if __name__ == "__main__":
    symbols = list_symbols()
    print(f"running {len(symbols)} symbols...")

    all_trades, per_symbol = [], []
    for i, sym in enumerate(symbols, 1):
        trades = run_backtest(get_bars(sym))
        if not trades:
            continue
        all_trades.extend(trades)
        s = summarise(trades, sym)
        per_symbol.append(s)
        if i % 50 == 0:
            print(f"  {i}/{len(symbols)}")

    print_summary(summarise(all_trades, "ALL SYMBOLS"))

    n_sym = len(per_symbol)
    print(f"\n  symbols traded {n_sym:>12,}")
    print(f"  notional used  {n_sym * CAPITAL:>12,}   <- NOT one portfolio; "
          f"{n_sym} separate simulations")

    pd.DataFrame(all_trades).to_csv("trades.csv", index=False)
    pd.DataFrame(per_symbol).to_csv("per_symbol.csv", index=False)
    print("\nwrote trades.csv and per_symbol.csv")