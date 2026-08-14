"""
PORTFOLIO BACKTEST engineINE
=========================

Nothing about the strategy is hardcoded. Everything comes from CONFIG.
The web form will produce exactly this dict.

WHAT IT DOES
------------
Two-stage selection, run at every rebalance date:

    636 companies  (whatever is in the database)
        |  stage 1: pick the most liquid N  (avg turnover)
     40 companies  (universe)
        |  stage 2: pick the top N by momentum
     20 companies  (portfolio)

Plus, every single day:
    - check stop-loss on every open position
    - mark the portfolio to market and record NAV

TIMING RULE (this is the important one)
---------------------------------------
A signal is computed from bar t's CLOSE.
The order is FILLED at bar t+1's OPEN.
You cannot trade at a price you only learn about after the market shuts.

RUN IT
------
    source venv/bin/activate
    python portfolio_engineine.py
"""

import os
import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from db import db as engine

# ======================================================================
# CONFIG  --  every one of these becomes a field in the web form
# ======================================================================
CONFIG = {
    # --- period ---
    "start":              "2018-07-05",
    "end":                "2026-07-03",

    # --- stage 1: which companies are eligible at all ---
    "universe_size":      40,          # keep the top N most liquid
    "universe_lookback":  60,          # days of turnover to average

    # --- stage 2: which of those we actually hold ---
    "hold_count":         20,          # target number of positions
    "momentum_lookback":  60,          # days of return used as the score
    "buffer_rank":        25,          # an existing holding survives to this rank

    # --- money ---
    "capital":            2_000_000,   # 20 lakh
    "max_weight":         0.08,        # no company above 8% of NAV

    # --- risk ---
    "stop_loss_pct":      8.0,         # exit a position down this much
    "stop_check":         "close",     # "close" or "intraday"

    # --- mechanics ---
    "rebalance":          "monthly",   # "monthly" | "weekly" | "daily"
    "cost_bps":           15,          # per side: brokerage + STT + slippage
}




# ======================================================================
# 1. LOAD DATA
# ======================================================================
def load_matrices(cfg):
    """
    Pull every bar once and reshape into date x symbol grids.
    A NaN means the company was not trading that day (not yet listed,
    suspended, etc). That is how "this company did not exist in 2018"
    is handled -- it is simply NaN, and NaN never gets selected.
    """
   
    df = pd.read_sql(
        "SELECT symbol, d, open, high, low, close, volume "
        "FROM bar_daily WHERE d BETWEEN %(s)s AND %(e)s",
        engine, params={"s": cfg["start"], "e": cfg["end"]},
    )
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)

    M = {c: df.pivot(index="d", columns="symbol", values=c).sort_index()
         for c in ["open", "high", "low", "close", "volume"]}
    M["turnover"] = M["close"] * M["volume"]
    return M


# ======================================================================
# 2. REBALANCE CALENDAR
# ======================================================================
def rebalance_dates(dates, how):
    """Which days do we re-pick the portfolio on?"""
    s = pd.Series(dates, index=pd.DatetimeIndex(dates))
    if how == "daily":
        return set(dates)
    if how == "weekly":
        return set(s.groupby(s.index.to_period("W")).last())
    return set(s.groupby(s.index.to_period("M")).last())   # monthly


# ======================================================================
# 3. THE TWO SELECTION STAGES
# ======================================================================
def pick_universe(M, i, cfg):
    """Stage 1: the most liquid companies over the lookback window."""
    lb = cfg["universe_lookback"]
    if i < lb:
        return []
    window = M["turnover"].iloc[i - lb: i]

    # a company must have traded on essentially every day of the window
    liquid = window.dropna(axis=1, thresh=int(lb * 0.9)).mean()
    return liquid.nlargest(cfg["universe_size"]).index.tolist()


def momentum_scores(M, i, universe, cfg):
    """Stage 2 input: return over the momentum lookback, per company."""
    lb = cfg["momentum_lookback"]
    if i < lb:
        return pd.Series(dtype=float)

    now  = M["close"].iloc[i][universe]
    then = M["close"].iloc[i - lb][universe]
    return (now / then - 1).dropna().sort_values(ascending=False)


def choose_portfolio(scores, held, cfg):
    """
    Turn a ranking into a target list of companies.

    The buffer is why this is not just "take the top 20". A company you
    already own keeps its slot until it falls past buffer_rank. Without
    that, a name oscillating around rank 20 gets traded every month and
    the costs eat the strategy.
    """
    ranks  = {sym: r for r, sym in enumerate(scores.index, 1)}
    keep   = [s for s in held if ranks.get(s, 10**9) <= cfg["buffer_rank"]]
    slots  = cfg["hold_count"] - len(keep)
    adds   = [s for s in scores.index if s not in keep][:max(slots, 0)]
    return keep + adds


# ======================================================================
# 4. THE engineINE
# ======================================================================
def run(cfg):
    M      = load_matrices(cfg)
    dates  = list(M["close"].index)
    rebals = rebalance_dates(dates, cfg["rebalance"])

    def price(series, sym):                      # <- ye teen line jodo
        v = series.get(sym, 0.0)
        return 0.0 if pd.isna(v) else float(v)


    cash      = float(cfg["capital"])
    positions = {}            # symbol -> {"shares": int, "entry": float}
    pending   = []            # orders raised today, filled tomorrow at open
    stopped   = set()         # stopped out; blocked until next rebalance

    trades, nav_rows = [], []
    cost_rate = cfg["cost_bps"] / 10_000.0
    stop_frac = cfg["stop_loss_pct"] / 100.0

    for i, day in enumerate(dates):
        op    = M["open"].iloc[i]
        close = M["close"].iloc[i]
        low   = M["low"].iloc[i]

        # ------------------------------------------------------------------
        # STEP 1  fill yesterday's orders at TODAY'S OPEN
        # ------------------------------------------------------------------
        for order in pending:
            sym, side, qty = order["symbol"], order["side"], order["qty"]
            px = op.get(sym, np.nan)
            if np.isnan(px) or qty <= 0:
                continue

            if side == "SELL" and sym in positions:
                qty  = min(qty, positions[sym]["shares"])
                cost = qty * px * cost_rate
                cash += qty * px - cost
                trades.append({
                    "date": day, "symbol": sym, "side": "SELL",
                    "qty": qty, "price": px, "cost": cost,
                    "pnl": qty * (px - positions[sym]["entry"]) - cost,
                    "reason": order["reason"],
                })
                positions[sym]["shares"] -= qty
                if positions[sym]["shares"] == 0:
                    del positions[sym]

            elif side == "BUY":
                cost = qty * px * cost_rate
                if qty * px + cost > cash:                 # can't overspend
                    qty = int((cash / (px * (1 + cost_rate))) // 1)
                    cost = qty * px * cost_rate
                if qty <= 0:
                    continue
                cash -= qty * px + cost
                if sym in positions:                       # blended entry
                    old = positions[sym]
                    tot = old["shares"] + qty
                    positions[sym] = {
                        "shares": tot,
                        "entry": (old["entry"] * old["shares"] + px * qty) / tot,
                    }
                else:
                    positions[sym] = {"shares": qty, "entry": px}
                trades.append({
                    "date": day, "symbol": sym, "side": "BUY",
                    "qty": qty, "price": px, "cost": cost,
                    "pnl": 0.0, "reason": order["reason"],
                })
        pending = []

        # ------------------------------------------------------------------
        # STEP 2  stop-loss check on every open position
        # ------------------------------------------------------------------
        for sym, pos in list(positions.items()):
            trigger = pos["entry"] * (1 - stop_frac)

            if cfg["stop_check"] == "intraday":
                # a resting stop order: it fires the moment price touches it
                if not np.isnan(low.get(sym, np.nan)) and low[sym] <= trigger:
                    fill = min(trigger, op.get(sym, trigger))   # gap-down aware
                    qty  = pos["shares"]
                    cost = qty * fill * cost_rate
                    cash += qty * fill - cost
                    trades.append({
                        "date": day, "symbol": sym, "side": "SELL",
                        "qty": qty, "price": fill, "cost": cost,
                        "pnl": qty * (fill - pos["entry"]) - cost,
                        "reason": "STOP",
                    })
                    del positions[sym]
                    stopped.add(sym)
            else:
                # checked on the close, so the exit happens tomorrow at open
                px = close.get(sym, np.nan)
                if not np.isnan(px) and px <= trigger:
                    pending.append({"symbol": sym, "side": "SELL",
                                    "qty": pos["shares"], "reason": "STOP"})
                    stopped.add(sym)

        # ------------------------------------------------------------------
        # STEP 3  rebalance: decide tomorrow's target portfolio
        # ------------------------------------------------------------------
        if day in rebals:
            stopped.clear()
            universe = pick_universe(M, i, cfg)
            scores   = momentum_scores(M, i, universe, cfg)

            if len(scores):
                held   = [s for s in positions if s not in
                          {o["symbol"] for o in pending}]
                target = choose_portfolio(scores, held, cfg)

                nav    = cash + sum(p["shares"] * price(close, 0)
                                    for s, p in positions.items())
                weight = min(1.0 / max(len(target), 1), cfg["max_weight"])

                # sell what is no longer wanted
                for sym, pos in positions.items():
                    if sym not in target:
                        pending.append({"symbol": sym, "side": "SELL",
                                        "qty": pos["shares"],
                                        "reason": "REBAL_EXIT"})

                # size what is wanted
                for sym in target:
                    px = close.get(sym, np.nan)
                    if pd.isna(px) or px <= 0:
                        continue
                    want = int((nav * weight) // px)
                    have = positions.get(sym, {}).get("shares", 0)
                    if want > have:
                        pending.append({"symbol": sym, "side": "BUY",
                                        "qty": want - have,
                                        "reason": "REBAL_ENTRY"})
                    elif want < have:
                        pending.append({"symbol": sym, "side": "SELL",
                                        "qty": have - want,
                                        "reason": "REBAL_TRIM"})

        # ------------------------------------------------------------------
        # STEP 4  mark to market, record today's NAV
        # ------------------------------------------------------------------
        mtm = sum(p["shares"] * price(close, 0) for s, p in positions.items())
        nav_rows.append({"date": day, "cash": cash, "mtm": mtm,
                         "nav": cash + mtm, "positions": len(positions)})

    return pd.DataFrame(trades), pd.DataFrame(nav_rows).set_index("date")


# ======================================================================
# 5. SUMMARY NUMBERS  --  what the PM asked to see first
# ======================================================================
def summarise(nav, trades, cfg):
    n     = nav["nav"]
    years = len(n) / 252.0
    ret   = n.iloc[-1] / n.iloc[0] - 1
    dd    = (n / n.cummax() - 1).min()
    daily = n.pct_change().dropna()

    sells = trades[trades.side == "SELL"] if len(trades) else pd.DataFrame()

    return {
        "Start NAV":        n.iloc[0],
        "End NAV":          n.iloc[-1],
        "Total return %":   ret * 100,
        "CAGR %":           ((1 + ret) ** (1 / years) - 1) * 100,
        "Max drawdown %":   dd * 100,
        "Volatility %":     daily.std() * np.sqrt(252) * 100,
        "Sharpe":           daily.mean() / daily.std() * np.sqrt(252) if daily.std() else 0,
        "Trades":           len(trades),
        "Win rate %":       (sells.pnl > 0).mean() * 100 if len(sells) else 0,
        "Total costs":      trades["cost"].sum() if len(trades) else 0,
        "Avg positions":    nav["positions"].mean(),
    }


if __name__ == "__main__":
    print("running backtest...")
    trades, nav = run(CONFIG)

    print("\n=== SUMMARY ===")
    for k, v in summarise(nav, trades, CONFIG).items():
        print(f"  {k:<18} {v:>14,.2f}")

    trades.to_csv("pf_trades.csv", index=False)
    nav.to_csv("pf_nav.csv")
    print("\nwrote pf_trades.csv and pf_nav.csv")