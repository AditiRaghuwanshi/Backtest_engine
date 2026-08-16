import os
import uuid
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import storage
from db import db

app = FastAPI()

# ----------------------------------------------------------------------
# CORS
# ----------------------------------------------------------------------
ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ORIGINS],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------------------------
# WORKER POOL
#
# Yahi asli fix hai. Backtest ALAG process mein chalta hai.
# Web process khaali rehta hai aur requests ka jawab deta rehta hai,
# isliye Railway usko mara hua nahi samajhta.
#
# max_workers=1 -- ek waqt mein ek hi backtest. RAM bachti hai.
# ----------------------------------------------------------------------
pool = ProcessPoolExecutor(max_workers=1)


# ----------------------------------------------------------------------
# CONFIG  --  form ka har box yahan ek line
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
# YE FUNCTION ALAG PROCESS MEIN CHALTA HAI
#
# Isliye ye module ke top level pe hona chahiye (andar nested nahi),
# warna Python isko doosre process ko bhej nahi paata.
# ----------------------------------------------------------------------
def _worker(run_id: str, cfg: dict):
    from portfolio_engine import run, summarise

    meta = storage.load_meta(run_id) or {"run_id": run_id, "config": cfg}
    meta["status"] = "running"
    storage.save_meta(run_id, meta)

    try:
        trades, nav = run(cfg)
        summary = summarise(nav, trades, cfg)
        summary = {k: (None if pd.isna(v) else float(v))
                   for k, v in summary.items()}

        storage.save_frames(run_id, trades, nav)

        meta["result"] = summary
        meta["trades"] = len(trades)
        meta["status"] = "done"
    except Exception as e:
        meta["status"] = "failed"
        meta["error"] = f"{type(e).__name__}: {e}"

    meta["finished_at"] = datetime.now().isoformat()
    storage.save_meta(run_id, meta)


# ----------------------------------------------------------------------
# ENDPOINTS
# ----------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/companies")
def get_companies():
    df = pd.read_sql("SELECT DISTINCT symbol FROM bar_daily ORDER BY symbol", db)
    return {"count": len(df), "companies": df["symbol"].tolist()}


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


@app.post("/runs")
def start_run(cfg: Config):
    run_id = str(uuid.uuid4())[:8]

    storage.save_meta(run_id, {
        "run_id": run_id,
        "status": "queued",
        "config": cfg.model_dump(),
        "started_at": datetime.now().isoformat(),
    })

    # alag process ko kaam de do -- yahan wait nahi karte
    pool.submit(_worker, run_id, cfg.model_dump())

    return {"run_id": run_id, "status": "queued"}


@app.get("/runs")
def list_runs():
    return storage.list_metas()


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    meta = storage.load_meta(run_id)
    if meta is None:
        raise HTTPException(404, "run not found")
    return meta


@app.get("/runs/{run_id}/nav")
def run_nav(run_id: str):
    df = storage.load_nav(run_id)
    if df is None:
        raise HTTPException(404, "not ready")
    df["date"] = df["date"].astype(str)
    return df[["date", "nav", "cash", "positions"]].round(2).to_dict("records")


@app.get("/runs/{run_id}/trades")
def run_trades(run_id: str, symbol: str | None = None, reason: str | None = None):
    df = storage.load_trades(run_id)
    if df is None:
        raise HTTPException(404, "not ready")
    if symbol:
        df = df[df.symbol == symbol.upper()]
    if reason:
        df = df[df.reason == reason]
    return {"total": len(df), "rows": df.round(2).to_dict("records")}


@app.get("/runs/{run_id}/companies")
def run_companies(run_id: str):
    df = storage.load_trades(run_id)
    if df is None:
        raise HTTPException(404, "not ready")
    out = (df.groupby("symbol")
             .agg(net_pnl=("pnl", "sum"),
                  costs=("cost", "sum"),
                  trades=("side", "size"))
             .sort_values("net_pnl", ascending=False)
             .reset_index())
    return out.round(2).to_dict("records")


@app.get("/runs/{run_id}/holdings/{date}")
def run_holdings(run_id: str, date: str):
    df = storage.load_trades(run_id)
    if df is None:
        raise HTTPException(404, "not ready")

    df = df[df.date.astype(str) <= date]
    held = {}
    for _r, t in df.iterrows():
        qty = t.qty if t.side == "BUY" else -t.qty
        held[t.symbol] = held.get(t.symbol, 0) + qty

    open_now = {s: int(q) for s, q in held.items() if q > 0}
    return {"date": date, "count": len(open_now), "holdings": open_now}