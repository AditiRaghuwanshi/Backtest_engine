import uuid

import pandas as pd
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from db import db

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# saare runs yahan (server restart pe mit jayenge)
runs = {}


# ----------------------------------------------------------------------
# CONFIG  --  form ka har box yahan ek line banega
# ----------------------------------------------------------------------
class Config(BaseModel):
    start:             str   = "2018-07-05"
    end:               str   = "2026-07-03"
    universe_size:     int   = 40
    universe_lookback: int   = 60
    hold_count:        int   = 20
    momentum_lookback: int   = 60
    buffer_rank:       int   = 25
    capital:           float = 2000000
    max_weight:        float = 0.08
    stop_loss_pct:     float = 8.0
    stop_check:        str   = "close"
    rebalance:         str   = "monthly"
    cost_bps:          float = 15


# ----------------------------------------------------------------------
# 1. HEALTH
# ----------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


# ----------------------------------------------------------------------
# 2. COMPANIES  --  saari companies ki list
# ----------------------------------------------------------------------
@app.get("/companies")
def get_companies():
    df = pd.read_sql(
        "SELECT DISTINCT symbol FROM bar_daily ORDER BY symbol", db
    )
    return {"count": len(df), "companies": df["symbol"].tolist()}


# ----------------------------------------------------------------------
# 3. ONE COMPANY  --  ek company ka price data
# ----------------------------------------------------------------------
@app.get("/companies/{symbol}")
def get_company(symbol: str, limit: int = 10):
    df = pd.read_sql(
        "SELECT d, open, high, low, close, volume FROM bar_daily "
        "WHERE symbol = %(s)s ORDER BY d DESC LIMIT %(n)s",
        db, params={"s": symbol.upper(), "n": limit},
    )
    if df.empty:
        raise HTTPException(404, f"{symbol} not found")
    return {"symbol": symbol.upper(), "rows": df.to_dict("records")}


# ----------------------------------------------------------------------
# 4. BACKTEST  --  peeche chalta hai
# ----------------------------------------------------------------------
def do_backtest(run_id: str):
    """Ye PEECHE chalta hai. Browser iska intezaar nahi karta."""
    runs[run_id]["status"] = "running"

    try:
        from portfolio_engine import run, summarise

        cfg = runs[run_id]["config"]
        trades, nav = run(cfg)
        summary = summarise(nav, trades, cfg)

        # NaN JSON mein nahi jaata, isliye None bana do
        summary = {k: (None if pd.isna(v) else float(v))
                   for k, v in summary.items()}

        runs[run_id]["result"] = summary
        runs[run_id]["trades"] = len(trades)
        runs[run_id]["trades_df"] = trades      # <- ye naya
        runs[run_id]["nav_df"] = nav            # <- ye naya
        runs[run_id]["status"] = "done"

    except Exception as e:
        runs[run_id]["status"] = "failed"
        runs[run_id]["error"] = str(e)


@app.post("/runs")
def start_run(cfg: Config, background: BackgroundTasks):
    run_id = str(uuid.uuid4())[:8]

    runs[run_id] = {
        "run_id": run_id,
        "status": "queued",
        "config": cfg.model_dump(),
    }

    background.add_task(do_backtest, run_id)

    return {"run_id": run_id, "status": "queued"}

@app.get("/runs/{run_id}")
def get_run(run_id: str):
    if run_id not in runs:
        raise HTTPException(404, "run not found")
    r = runs[run_id]
    return {k: v for k, v in r.items() if not k.endswith("_df")}


@app.get("/runs")
def list_runs():
    return list(runs.values())


    # ----------------------------------------------------------------------
# 5. HAR TRADE  --  kaunsi company, kab, kitne mein, kyun
# ----------------------------------------------------------------------
@app.get("/runs/{run_id}/trades")
def run_trades(run_id: str, symbol: str | None = None, reason: str | None = None):
    if run_id not in runs or "trades_df" not in runs[run_id]:
        raise HTTPException(404, "not ready")

    df = runs[run_id]["trades_df"]
    if symbol:
        df = df[df.symbol == symbol.upper()]
    if reason:
        df = df[df.reason == reason]

    return {"total": len(df), "rows": df.round(2).to_dict("records")}


# ----------------------------------------------------------------------
# 6. COMPANY-WISE  --  kisne kitna kamaya / gawaya
# ----------------------------------------------------------------------
@app.get("/runs/{run_id}/companies")
def run_companies(run_id: str):
    if run_id not in runs or "trades_df" not in runs[run_id]:
        raise HTTPException(404, "not ready")

    df = runs[run_id]["trades_df"]
    out = (df.groupby("symbol")
             .agg(net_pnl=("pnl", "sum"),
                  costs=("cost", "sum"),
                  trades=("side", "size"))
             .sort_values("net_pnl", ascending=False)
             .reset_index())

    return out.round(2).to_dict("records")


# ----------------------------------------------------------------------
# 7. KISI DIN KA PORTFOLIO  --  us din kaunsi companies paas thi
# ----------------------------------------------------------------------
@app.get("/runs/{run_id}/holdings/{date}")
def run_holdings(run_id: str, date: str):
    if run_id not in runs or "trades_df" not in runs[run_id]:
        raise HTTPException(404, "not ready")

    df = runs[run_id]["trades_df"]
    df = df[df.date.astype(str) <= date]

    held = {}
    for _, t in df.iterrows():
        qty = t.qty if t.side == "BUY" else -t.qty
        held[t.symbol] = held.get(t.symbol, 0) + qty

    open_now = {s: int(q) for s, q in held.items() if q > 0}
    return {"date": date, "count": len(open_now), "holdings": open_now}



@app.get("/runs/{run_id}/nav")
def run_nav(run_id: str):
    if run_id not in runs or "nav_df" not in runs[run_id]:
        raise HTTPException(404, "not ready")

    df = runs[run_id]["nav_df"].reset_index()
    df["date"] = df["date"].astype(str)
    return df[["date", "nav", "cash", "positions"]].round(2).to_dict("records")