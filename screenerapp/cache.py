"""Tables the pages need at start-up, derived from the features package.

    .venv\\Scripts\\python.exe -m screenerapp.cache

app.py runs this by itself whenever the features build has changed (a new
`build_id` in its manifest), so it is rarely needed by hand. It takes ~15 s:

* snapshot.parquet - one row per ticker, for the screener and the DCF: the newest
  price row, the fundamentals of the quarter in force that day (`fundamental_date`
  is its period end) and the valuation ratios of the ticker's last day on which
  they were valid (`valuation_date`). After the fundamentals download the ratios
  go blank once the next report is due (`fund_stale`), so the newest row alone
  would show almost none.
* trading_dates.parquet - the US session calendar the date pickers snap to.

Amounts stay in the trading currency here; the pages convert where they compare
tickers (see data.to_usd).
"""

from __future__ import annotations

import pandas as pd

import features
from features.views import screener

from . import config, indicators

# Tickers per price read. Bounds memory: whole histories of ~50 tickers at a time.
BATCH_TICKERS = 50


def is_fresh() -> bool:
    """True when the cache was built from the live features build."""
    if not config.BUILD_ID_FILE.exists():
        return False
    return config.BUILD_ID_FILE.read_text().strip() == features.get_manifest()["build_id"]


def _newest(rows: pd.DataFrame) -> pd.DataFrame:
    return rows.loc[rows.groupby("ticker")["date"].idxmax()]


def snapshot() -> pd.DataFrame:
    catalog = indicators.build_catalog()
    price = [c for c, i in catalog.items() if i.source == indicators.SOURCE_PRICE]
    fundamental = [c for c, i in catalog.items() if i.source == indicators.SOURCE_FUNDAMENTAL]
    valuation = [c for c in price if catalog[c].is_valuation]

    # The view's rules run on the ~900 picked rows only, not on all 6.8 M price rows:
    # read its canonical inputs, pick the rows, then apply it.
    view_columns = [*price, "fx_per_usd", "fund_date"]
    refs = screener.VIEW.needed(view_columns)
    daily = [r for r in refs if not r.startswith(indicators.QUARTERLY)]
    quarterly_columns = [r.removeprefix(indicators.QUARTERLY) for r in refs if r not in daily]
    quarterly = features.read_table(
        "fundamentals_quarterly",
        list(dict.fromkeys(quarterly_columns + indicators.quarterly_inputs(fundamental))),
    )

    tickers = features.read_table("universe", [])["ticker"].tolist()
    latest, valued = [], []
    for start in range(0, len(tickers), BATCH_TICKERS):
        rows = features.read_table("price_daily", daily, tickers=tickers[start : start + BATCH_TICKERS])
        latest.append(_newest(rows))
        valued.append(_newest(rows[rows["fund_date"].notna() & ~rows["fund_stale"]]))
    latest = screener.apply(pd.concat(latest, ignore_index=True), view_columns, quarterly=quarterly)
    valued = screener.apply(pd.concat(valued, ignore_index=True), valuation, quarterly=quarterly)

    quarters = indicators.apply_quarterly_rules(quarterly, fundamental)[["ticker", "date", *fundamental]]
    snap = (
        latest.drop(columns=valuation)
        .merge(valued.rename(columns={"date": "valuation_date"}), on="ticker", how="left")
        .merge(
            quarters.rename(columns={"date": "fund_date"}),
            on=["ticker", "fund_date"],
            how="left",
            validate="m:1",
        )
        .rename(columns={"fund_date": "fundamental_date"})
    )
    return snap.sort_values("ticker", ignore_index=True)


def trading_dates() -> pd.DataFrame:
    """The dates US-listed tickers traded.

    Stocks listed abroad trade on US holidays; a date on which only they traded
    would make the heatmap and the distribution page come up nearly empty. A
    handful of stray rows on a US holiday (two tickers on Thanksgiving 2024) do
    not make a session either: a date needs a fifth of the usual ticker count.
    """
    universe = features.read_table("universe", ["exchange"])
    us = universe.loc[universe["exchange"].eq("US"), "ticker"].tolist()
    counts = features.read_table("price_daily", [], tickers=us)["date"].value_counts().sort_index()
    usual = counts.rolling(21, center=True, min_periods=5).median()
    return pd.DataFrame({"date": counts.index[counts >= 0.2 * usual]})


def build() -> None:
    build_id = features.get_manifest()["build_id"]
    print(f"Building the app cache for features build {build_id} ...", flush=True)
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    snapshot().to_parquet(config.SNAPSHOT_FILE, index=False)
    trading_dates().to_parquet(config.TRADING_DATES_FILE, index=False)
    # Written last, so an interrupted build is still seen as stale.
    config.BUILD_ID_FILE.write_text(build_id)
    print("Cache ready.", flush=True)


if __name__ == "__main__":
    build()
