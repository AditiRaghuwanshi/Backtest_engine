"""
COMPANY-WISE BREAKDOWN
======================

pf_trades.csv has every single trade. This rolls it up per company so you
can answer: which companies made money, which lost, and why did we exit.

    python attribution.py
"""

import pandas as pd

t = pd.read_csv("pf_trades.csv", parse_dates=["date"])
sells = t[t.side == "SELL"]

# ----------------------------------------------------------------------
# 1. COMPANY-WISE PROFIT / LOSS
# ----------------------------------------------------------------------
per_co = (
    t.groupby("symbol")
     .agg(
         net_pnl    = ("pnl",  "sum"),
         costs      = ("cost", "sum"),
         trades     = ("side", "size"),
         times_held = ("reason", lambda r: (r == "REBAL_ENTRY").sum()),
         first_seen = ("date", "min"),
         last_seen  = ("date", "max"),
     )
     .sort_values("net_pnl", ascending=False)
)

print("\n" + "=" * 70)
print("TOP 15 COMPANIES  (made the most money)")
print("=" * 70)
print(per_co.head(15).to_string(
    formatters={"net_pnl": "{:,.0f}".format, "costs": "{:,.0f}".format}))

print("\n" + "=" * 70)
print("BOTTOM 15 COMPANIES  (lost the most money)")
print("=" * 70)
print(per_co.tail(15).to_string(
    formatters={"net_pnl": "{:,.0f}".format, "costs": "{:,.0f}".format}))

print(f"\n  companies traded : {len(per_co)}")
print(f"  made money       : {(per_co.net_pnl > 0).sum()}")
print(f"  lost money       : {(per_co.net_pnl <= 0).sum()}")
print(f"  total net pnl    : {per_co.net_pnl.sum():,.0f}")

# ----------------------------------------------------------------------
# 2. WHY DID WE EXIT?  (this is where the strategy leaks money)
# ----------------------------------------------------------------------
by_reason = sells.groupby("reason").agg(
    count   = ("pnl", "size"),
    win_pct = ("pnl", lambda s: (s > 0).mean() * 100),
    total   = ("pnl", "sum"),
    average = ("pnl", "mean"),
)

print("\n" + "=" * 70)
print("EXIT REASONS")
print("=" * 70)
print(by_reason.to_string(formatters={
    "win_pct": "{:.1f}%".format,
    "total":   "{:,.0f}".format,
    "average": "{:,.0f}".format}))

# ----------------------------------------------------------------------
# 3. REAL WIN RATE  (trims excluded -- they inflate the number)
# ----------------------------------------------------------------------
real = sells[sells.reason.isin(["STOP", "REBAL_EXIT"])]
print(f"\n  real exits       : {len(real)}")
print(f"  real win rate    : {(real.pnl > 0).mean() * 100:.1f}%"
      f"   <- the honest number")

# ----------------------------------------------------------------------
# 4. YEAR BY YEAR
# ----------------------------------------------------------------------
yearly = sells.assign(year=sells.date.dt.year).groupby("year").agg(
    exits = ("pnl", "size"),
    pnl   = ("pnl", "sum"),
)
print("\n" + "=" * 70)
print("YEAR BY YEAR")
print("=" * 70)
print(yearly.to_string(formatters={"pnl": "{:,.0f}".format}))

per_co.to_csv("company_breakdown.csv")
print("\nwrote company_breakdown.csv")