import os
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    password = os.getenv("PGPASSWORD")
    DATABASE_URL = f"postgresql+psycopg2://postgres:{password}@localhost:5432/backtest"

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

db = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=2)