import os
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

PASSWORD = os.getenv("PGPASSWORD")
db = create_engine(f"postgresql+psycopg2://postgres:{PASSWORD}@localhost:5432/backtest")