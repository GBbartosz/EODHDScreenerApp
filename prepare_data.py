"""Build step - turns the feature files into what the app loads at start-up.

    .venv\\Scripts\\python.exe prepare_data.py

building_features.py runs this at the end, so a new data drop needs only that
one command; run this on its own only after changing something in here.

The price feature file is ~0.7 GB, far too slow to load every time the app
starts. This script precomputes the one thing the screener needs eagerly - the
most recent row per ticker, with fundamentals and sector attached - plus the
session calendar and a small manifest describing the data. Long history is *not*
copied: the app reads it lazily from the feature files, which are sorted by ticker.

Outputs land in data/processed/.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import pyarrow.parquet as pq

from screenerapp import config

# Big enough to be efficient, small enough to stay well inside memory.
BATCH_ROWS = 250_000

TICKER_COLUMNS = ["ticker", "name", "type", "exchange", "currency", "is_delisted", config.SECTOR_COL, config.INDUSTRY_COL]

# tickers.parquet classifies a reused symbol by its current holder. For these two
# the data is the old company's (cut at the takeover, see TRUNCATE_TICKERS in
# building_features.py), so the sector has to be the old company's too.
SECTOR_OVERRIDES = {
    "MON": ("Basic Materials", "Agricultural Inputs"),  # Monsanto, not Monument Circle Acquisition
    "XL": ("Financial Services", "Insurance - Property & Casualty"),  # XL Group, not XL Fleet
}


def log(message: str) -> None:
    print(f"  {message}", flush=True)


def price_date_bounds(path) -> pd.DataFrame:
    """First and last price date per ticker.

    Only two columns are read and the grouping happens in Arrow, so this stays
    cheap even though the file has millions of rows. The relative-performance
    page uses these bounds to pick a default window without touching history.
    """
    table = pq.read_table(path, columns=["ticker", "date"])
    grouped = table.group_by("ticker").aggregate([("date", "min"), ("date", "max")])
    return (
        grouped.to_pandas()
        .rename(columns={"date_min": "first_price_date", "date_max": "last_price_date"})
        .set_index("ticker")
    )


def load_stocks(bounds: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Sector/industry map, restricted to tickers that actually have prices."""
    stocks = pd.read_parquet(config.RAW_TICKERS, columns=TICKER_COLUMNS)
    stocks = stocks[stocks["ticker"].isin(bounds.index)].copy()

    stocks["first_price_date"] = stocks["ticker"].map(bounds["first_price_date"])
    stocks["last_price_date"] = stocks["ticker"].map(bounds["last_price_date"])
    stocks["is_active"] = stocks["last_price_date"] >= cutoff

    for ticker, (sector, industry) in SECTOR_OVERRIDES.items():
        stocks.loc[stocks["ticker"] == ticker, [config.SECTOR_COL, config.INDUSTRY_COL]] = [sector, industry]
    for column in (config.SECTOR_COL, config.INDUSTRY_COL):
        stocks[column] = stocks[column].fillna("Unclassified")

    return stocks.sort_values("ticker", ignore_index=True)


def latest_rows(path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Most recent row per ticker, and most recent row with a usable valuation.

    Read in batches to keep memory flat. The file is sorted by (ticker, date), so
    a ticker's last row in a batch is its most recent so far; concatenating the
    per-batch candidates in order and taking the last one again resolves tickers
    that span a batch boundary.

    "Usable valuation" means a quarter is attached and not stale: after the
    fundamentals download, P/E and friends go blank once the next report is due,
    so the last usable day is where the screener takes them from.
    """
    parquet_file = pq.ParquetFile(path)
    latest, valued = [], []
    valued_columns = ["ticker", "date", *config.VALUATION_COLUMNS]

    for batch in parquet_file.iter_batches(batch_size=BATCH_ROWS):
        frame = batch.to_pandas()
        latest.append(frame.groupby("ticker", sort=False).tail(1))
        usable = frame["fund_date"].notna() & ~frame["fund_stale"]
        valued.append(frame.loc[usable, valued_columns].groupby("ticker", sort=False).tail(1))

    def last_per_ticker(candidates: list[pd.DataFrame]) -> pd.DataFrame:
        return pd.concat(candidates, ignore_index=True).groupby("ticker", sort=False).tail(1).reset_index(drop=True)

    return last_per_ticker(latest), last_per_ticker(valued)


def trading_dates(path, stocks: pd.DataFrame) -> pd.DataFrame:
    """The US session calendar - the dates US-listed tickers traded.

    The universe also holds stocks listed abroad, which trade on US holidays. A
    date on which only they traded would make the heatmap and the distribution
    page come up nearly empty, so the date pickers snap to US sessions instead.
    A handful of stray rows on US holidays (two tickers on Thanksgiving 2024) do
    not make a session either: a date needs a fifth of the usual ticker count.
    """
    us = stocks.loc[stocks["exchange"].eq("US"), "ticker"]
    table = pq.read_table(path, columns=["ticker", "date"], filters=[("ticker", "in", list(us))])
    counts = table.column("date").to_pandas().value_counts().sort_index()
    usual = counts.rolling(21, center=True, min_periods=5).median()
    sessions = counts.index[counts >= 0.2 * usual]
    return pd.DataFrame({"date": sessions})


def main() -> None:
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    for path in (config.FUNDAMENTAL_FEATURES, config.PRICE_FEATURES):
        if not path.exists():
            raise SystemExit(f"Missing {path.name} - run building_features.py first.")
    if not config.RAW_TICKERS.exists():
        raise SystemExit(f"Missing raw data file: {config.RAW_TICKERS}")

    print("Preparing data")

    # --- prices: newest row per ticker -------------------------------------
    log("scanning price history...")
    latest, valued = latest_rows(config.PRICE_FEATURES)
    log(f"{len(latest):,} tickers with prices")

    bounds = price_date_bounds(config.PRICE_FEATURES)
    oldest = bounds["first_price_date"].min()
    newest = bounds["last_price_date"].max()
    cutoff = newest - pd.Timedelta(days=config.ACTIVE_WINDOW_DAYS)
    log(f"prices span {oldest.date()} to {newest.date()} (active cutoff {cutoff.date()})")

    # --- fundamentals ------------------------------------------------------
    log("reading fundamentals...")
    fundamentals = pd.read_parquet(config.FUNDAMENTAL_FEATURES).drop(columns=["yq", "quarter"])
    log(f"{len(fundamentals):,} quarterly rows, {fundamentals['ticker'].nunique():,} tickers")
    fund_snapshot = pd.read_parquet(config.RAW_FUNDAMENTALS, columns=["fund_snapshot"])["fund_snapshot"].max()

    # --- join --------------------------------------------------------------
    # fund_date is the period end of the quarter current on the price day - unique
    # per ticker, so it joins one-to-one.
    screener = latest.merge(
        fundamentals.rename(columns={"date": "fundamental_date"}),
        left_on=["ticker", "fund_date"],
        right_on=["ticker", "fundamental_date"],
        how="left",
    ).drop(columns="fund_date")
    matched = screener["fundamental_date"].notna().sum()
    log(f"joined fundamentals onto {matched:,} of {len(screener):,} tickers")

    # Valuation ratios as of each ticker's last usable day, dated so the table
    # shows how old they are.
    valuation_columns = list(config.VALUATION_COLUMNS)
    screener = screener.drop(columns=valuation_columns).merge(
        valued.rename(columns={"date": "valuation_date"}), on="ticker", how="left"
    )
    behind = (screener["valuation_date"] < screener["date"]).sum()
    log(f"valuations: {screener['valuation_date'].notna().sum():,} tickers, "
        f"{behind:,} of them older than the latest price (fundamentals downloaded {fund_snapshot.date()})")

    stocks = load_stocks(bounds, cutoff)
    log(f"{int(stocks['is_active'].sum()):,} active / {len(stocks):,} tickers")

    screener = screener.merge(
        stocks[["ticker", config.SECTOR_COL, config.INDUSTRY_COL, "is_active"]],
        on="ticker",
        how="left",
    ).sort_values("ticker", ignore_index=True)

    sessions = trading_dates(config.PRICE_FEATURES, stocks)
    log(f"{len(sessions):,} US sessions")

    # --- write -------------------------------------------------------------
    screener.to_parquet(config.SCREENER_FILE, index=False)
    stocks.to_parquet(config.STOCKS_FILE, index=False)
    sessions.to_parquet(config.TRADING_DATES_FILE, index=False)

    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_tickers": int(len(stocks)),
        "n_active": int(stocks["is_active"].sum()),
        "price_date_min": str(oldest.date()),
        "price_date_max": str(newest.date()),
        "active_cutoff": str(cutoff.date()),
        "fund_snapshot": str(fund_snapshot.date()),
        "fundamental_columns": pq.read_schema(config.FUNDAMENTAL_FEATURES).names,
        "price_columns": pq.read_schema(config.PRICE_FEATURES).names,
    }
    with open(config.META_FILE, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)

    print("\nDone. Wrote:")
    for path in (config.SCREENER_FILE, config.STOCKS_FILE, config.TRADING_DATES_FILE, config.META_FILE):
        print(f"  {path.relative_to(config.PROJECT_ROOT)}  ({path.stat().st_size / 1024:.0f} KB)")
    print("\nStart the app with:  .venv\\Scripts\\python.exe app.py")


if __name__ == "__main__":
    main()
