import glob, os
import pandas as pd
from sqlalchemy import create_engine, text

PASSWORD = "Aditi1804!!"          # <-- your Postgres password
CSV_DIR  = "data"                  # folder is right here, relative path works

engine = create_engine(f"postgresql+psycopg2://postgres:{PASSWORD}@localhost:5432/backtest")

with engine.begin() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS bar_daily (
            symbol text NOT NULL,
            d      date NOT NULL,
            open   numeric(18,4), high  numeric(18,4),
            low    numeric(18,4), close numeric(18,4),
            volume bigint,
            PRIMARY KEY (symbol, d)
        );
    """))

files = sorted(glob.glob(os.path.join(CSV_DIR, "*.csv")))
print(f"found {len(files)} files")

for i, path in enumerate(files, 1):
    symbol = os.path.splitext(os.path.basename(path))[0]
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.rename(columns={"date": "d"})
    df["d"] = pd.to_datetime(df["d"], errors="coerce").dt.date
    df["symbol"] = symbol
    df = df[["symbol", "d", "open", "high", "low", "close", "volume"]].dropna(subset=["d"])

    df.to_sql("staging", engine, if_exists="replace", index=False)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO bar_daily
            SELECT symbol, d, open, high, low, close, volume FROM staging
            ON CONFLICT (symbol, d) DO NOTHING;
        """))
    print(f"{i}/{len(files)}  {symbol}  {len(df)} rows")

print("done")