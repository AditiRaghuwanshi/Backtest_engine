"""
RUN STORAGE
===========

Runs disk pe rakhe jaate hain, memory mein nahi.

Kyun? Kyunki backtest ab ALAG PROCESS mein chalta hai. Alag process
aapki Python dictionary tak nahi pahunch sakta -- par file dono
padh-likh sakte hain.

    runs/
      c3355cce.json          <- status, config, summary
      c3355cce_trades.csv    <- har trade
      c3355cce_nav.csv       <- rozana portfolio value
"""

import json
from pathlib import Path

import pandas as pd

RUNS_DIR = Path(__file__).parent / "runs"
RUNS_DIR.mkdir(exist_ok=True)


def save_meta(run_id, meta):
    (RUNS_DIR / f"{run_id}.json").write_text(json.dumps(meta, default=str))


def load_meta(run_id):
    f = RUNS_DIR / f"{run_id}.json"
    return json.loads(f.read_text()) if f.exists() else None


def list_metas():
    out = []
    for f in RUNS_DIR.glob("*.json"):
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            pass
    return sorted(out, key=lambda m: m.get("started_at", ""), reverse=True)


def save_frames(run_id, trades, nav):
    trades.to_csv(RUNS_DIR / f"{run_id}_trades.csv", index=False)
    nav.to_csv(RUNS_DIR / f"{run_id}_nav.csv")


def load_trades(run_id):
    f = RUNS_DIR / f"{run_id}_trades.csv"
    return pd.read_csv(f) if f.exists() else None


def load_nav(run_id):
    f = RUNS_DIR / f"{run_id}_nav.csv"
    return pd.read_csv(f) if f.exists() else None