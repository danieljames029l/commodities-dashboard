"""Pull daily futures closes from Yahoo Finance and upsert them into Postgres.

Safe to re-run: rows are keyed on (trade_date, symbol), so a re-run
refreshes recent closes and appends new days without duplicating.

    python load_prices.py            # 2021-01-01 to today
    python load_prices.py --dry-run  # fetch, save the CSV, no database
    python load_prices.py --offline  # load the last saved CSV, no network

Every fetch also saves data/prices.csv as a raw snapshot.
"""
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

SYMBOLS = {
    "BZ=F": "Brent crude ($/bbl)",
    "CL=F": "WTI crude ($/bbl)",
    "HO=F": "NY Harbor ULSD / heating oil ($/gal)",
    "RB=F": "RBOB gasoline ($/gal)",
}
START = "2021-01-01"
HERE = Path(__file__).parent
CSV = HERE / "data" / "prices.csv"


def load_env():
    env = {}
    for line in (HERE / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def fetch_one(symbol, end, attempts=6):
    for i in range(1, attempts + 1):
        try:
            hist = yf.Ticker(symbol).history(
                start=START, end=end, auto_adjust=False, timeout=30,
            )
            if not hist.empty:
                return hist
            reason = "empty response"
        except Exception as e:  # yfinance surfaces network drops as assorted errors
            reason = f"{type(e).__name__}: {str(e)[:80]}"
        print(f"  {symbol}: {reason} (attempt {i}/{attempts}), retrying")
        time.sleep(5 * i)
    raise RuntimeError(f"no data for {symbol} after {attempts} attempts")


def fetch():
    # yfinance's `end` is exclusive, so ask for tomorrow to include today.
    end = (date.today() + timedelta(days=1)).isoformat()
    frames = []
    for symbol in SYMBOLS:
        hist = fetch_one(symbol, end)
        frames.append(pd.DataFrame({
            "trade_date": hist.index.date,  # exchange-local date
            "symbol": symbol,
            "close_price": hist["Close"].round(4).to_numpy(),
        }))
    long = pd.concat(frames).dropna(subset=["close_price"])
    return long.sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def ensure_database(env):
    import psycopg2
    conn = psycopg2.connect(
        host=env["PGHOST"], port=env["PGPORT"], user=env["PGUSER"],
        password=env["PGPASSWORD"], dbname="postgres",
    )
    conn.autocommit = True  # CREATE DATABASE can't run inside a transaction
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (env["PGDATABASE"],))
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE "{env["PGDATABASE"]}"')
            print(f"created database {env['PGDATABASE']}")
    conn.close()


def upsert(env, df):
    import psycopg2
    from psycopg2.extras import execute_values
    conn = psycopg2.connect(
        host=env["PGHOST"], port=env["PGPORT"], user=env["PGUSER"],
        password=env["PGPASSWORD"], dbname=env["PGDATABASE"],
    )
    with conn, conn.cursor() as cur:
        cur.execute((HERE / "sql" / "01_schema.sql").read_text())
        execute_values(
            cur,
            """
            INSERT INTO prices (trade_date, symbol, close_price) VALUES %s
            ON CONFLICT (trade_date, symbol)
            DO UPDATE SET close_price = EXCLUDED.close_price
            """,
            list(df.itertuples(index=False, name=None)),
            page_size=2000,
        )
        cur.execute((HERE / "sql" / "02_views.sql").read_text())
        cur.execute("SELECT symbol, COUNT(*), MIN(trade_date), MAX(trade_date) FROM prices GROUP BY 1 ORDER BY 1")
        for row in cur.fetchall():
            print("  %-5s %5d rows  %s -> %s" % row)
    conn.close()


def main():
    if "--offline" in sys.argv:
        df = pd.read_csv(CSV, parse_dates=["trade_date"])
        df["trade_date"] = df["trade_date"].dt.date
        print(f"read {len(df)} rows from {CSV.name}")
    else:
        df = fetch()
        CSV.parent.mkdir(exist_ok=True)
        df.to_csv(CSV, index=False)
        print(f"fetched {len(df)} rows, saved {CSV.name}")
    print(df.groupby("symbol")["trade_date"].agg(["count", "min", "max"]).to_string())
    if "--dry-run" in sys.argv:
        return
    env = load_env()
    ensure_database(env)
    upsert(env, df)
    print("loaded and views refreshed")


if __name__ == "__main__":
    main()
