"""Build step - run this once after you replace anything in data/.

    .venv\\Scripts\\python.exe prepare_data.py

The raw price file is 1.2 GB, far too slow to load every time the app starts.
This script precomputes the one thing the screener needs eagerly - the most
recent row per ticker, with fundamentals and sector attached - and writes a
small manifest describing the data. Long history is *not* copied: the app reads
it lazily from the raw files, which are already sorted by ticker.

Outputs land in data/processed/.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import pyarrow.parquet as pq

from screenerapp import config

# Big enough to be efficient, small enough to stay well inside memory
# (250k rows x 56 float columns is roughly 110 MB).
BATCH_ROWS = 250_000


def log(message: str) -> None:
    print(f"  {message}", flush=True)


def price_date_bounds(path) -> pd.DataFrame:
    """First and last price date per ticker.

    Only two columns are read and the grouping happens in Arrow, so this stays
    cheap even though the file has five million rows. The relative-performance
    page uses these bounds to pick a default window without touching history.
    """
    table = pq.read_table(path, columns=["ticker", "date"])
    grouped = table.group_by("ticker").aggregate([("date", "min"), ("date", "max")])
    return (
        grouped.to_pandas()
        .rename(columns={"date_min": "first_price_date", "date_max": "last_price_date"})
        .set_index("ticker")
    )


def load_stocks(bounds: pd.DataFrame, cutoff: pd.Timestamp):
    """Sector/industry map, restricted to tickers that actually have prices."""
    stocks = pd.read_csv(config.RAW_STOCKS)
    stocks = stocks.drop(columns=[c for c in stocks.columns if c.startswith("Unnamed")])
    stocks = stocks.rename(columns={"Code": "ticker"})
    stocks = stocks[stocks["ticker"].isin(bounds.index)].copy()

    stocks["first_price_date"] = stocks["ticker"].map(bounds["first_price_date"])
    stocks["last_price_date"] = stocks["ticker"].map(bounds["last_price_date"])
    stocks["is_active"] = stocks["last_price_date"] >= cutoff

    for column in (config.SECTOR_COL, config.INDUSTRY_COL):
        stocks[column] = stocks[column].fillna("Unclassified")

    return stocks.sort_values("ticker", ignore_index=True)


def latest_price_rows(path) -> pd.DataFrame:
    """Most recent row per ticker, read in batches to keep memory flat.

    The file is sorted by (ticker, date), so a ticker's last row in a batch is
    its most recent so far; concatenating the per-batch candidates in order and
    taking the last one again resolves tickers that span a batch boundary.
    """
    parquet_file = pq.ParquetFile(path)
    candidates = []

    for batch in parquet_file.iter_batches(batch_size=BATCH_ROWS):
        frame = batch.to_pandas()
        candidates.append(frame.groupby("ticker", sort=False).tail(1))

    return (
        pd.concat(candidates, ignore_index=True)
        .groupby("ticker", sort=False)
        .tail(1)
        .reset_index(drop=True)
    )


def main() -> None:
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    for path in (config.RAW_FUNDAMENTALS, config.RAW_PRICES, config.RAW_STOCKS):
        if not path.exists():
            raise SystemExit(f"Missing raw data file: {path}")

    print("Preparing data")

    # --- prices: newest row per ticker -------------------------------------
    log("scanning price history...")
    latest = latest_price_rows(config.RAW_PRICES)
    price_columns = list(latest.columns)
    log(f"{len(latest):,} tickers with prices")

    bounds = price_date_bounds(config.RAW_PRICES)
    oldest = bounds["first_price_date"].min()
    newest = bounds["last_price_date"].max()
    cutoff = newest - pd.Timedelta(days=config.ACTIVE_WINDOW_DAYS)
    log(f"prices span {oldest.date()} to {newest.date()} (active cutoff {cutoff.date()})")

    # --- fundamentals ------------------------------------------------------
    log("reading fundamentals...")
    fundamentals = pd.read_parquet(config.RAW_FUNDAMENTALS)
    fundamental_columns = list(fundamentals.columns)

    # A ticker can file several quarters on the same day (catch-up filings), so
    # (ticker, filing_date) is not unique. Keep the newest quarter of each.
    fundamentals_latest = (
        fundamentals.sort_values(["ticker", "filing_date", "date"])
        .drop_duplicates(["ticker", "filing_date"], keep="last")
        .drop(columns=["yq", "quarter"])
        .rename(columns={"date": "fundamental_date"})
    )
    log(f"{len(fundamentals):,} quarterly rows, {fundamentals['ticker'].nunique():,} tickers")

    # --- join --------------------------------------------------------------
    screener = latest.merge(fundamentals_latest, on=["ticker", "filing_date"], how="left")
    matched = screener["fundamental_date"].notna().sum()
    log(f"joined fundamentals onto {matched:,} of {len(screener):,} tickers")

    stocks = load_stocks(bounds, cutoff)
    log(f"{int(stocks['is_active'].sum()):,} active / {len(stocks):,} tickers")

    screener = screener.merge(
        stocks[["ticker", config.SECTOR_COL, config.INDUSTRY_COL, "is_active"]],
        on="ticker",
        how="left",
    ).sort_values("ticker", ignore_index=True)

    # --- write -------------------------------------------------------------
    screener.to_parquet(config.SCREENER_FILE, index=False)
    stocks.to_parquet(config.STOCKS_FILE, index=False)

    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_tickers": int(len(stocks)),
        "n_active": int(stocks["is_active"].sum()),
        "price_date_min": str(oldest.date()),
        "price_date_max": str(newest.date()),
        "active_cutoff": str(cutoff.date()),
        "fundamental_columns": fundamental_columns,
        "price_columns": price_columns,
    }
    with open(config.META_FILE, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)

    print("\nDone. Wrote:")
    for path in (config.SCREENER_FILE, config.STOCKS_FILE, config.META_FILE):
        print(f"  {path.relative_to(config.PROJECT_ROOT)}  ({path.stat().st_size / 1024:.0f} KB)")
    print("\nStart the app with:  .venv\\Scripts\\python.exe app.py")


if __name__ == "__main__":
    main()
