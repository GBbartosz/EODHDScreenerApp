"""Data access layer.

Two different shapes of data, loaded two different ways:

* Small, always-needed tables (the screener snapshot, the sector map) are built
  by ``prepare_data.py`` and held in memory.
* Long history is read straight from the raw parquet files, one ticker and a
  handful of columns at a time. The raw price file is 1.2 GB and sorted by
  ticker, so parquet skips the row groups it doesn't need - a single ticker
  costs ~0.03s, and results are cached per ticker after that.

Everything returned by a cached function is shared, so treat it as read-only:
filter or copy before mutating.
"""

from __future__ import annotations

import functools
import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from . import config, indicators


class DataNotPreparedError(RuntimeError):
    """Raised when the build step has not been run yet."""


def _require(path):
    if not path.exists():
        raise DataNotPreparedError(
            f"Missing {path.name}. Run the build step first:\n"
            f"    .venv\\Scripts\\python.exe prepare_data.py"
        )
    return path


@functools.lru_cache(maxsize=1)
def get_meta() -> dict:
    with open(_require(config.META_FILE), encoding="utf-8") as fh:
        return json.load(fh)


@functools.lru_cache(maxsize=1)
def get_stocks() -> pd.DataFrame:
    """One row per ticker: sector, industry, and whether it still trades."""
    return pd.read_parquet(_require(config.STOCKS_FILE))


@functools.lru_cache(maxsize=1)
def get_screener() -> pd.DataFrame:
    """Latest available row per ticker, price and fundamentals joined."""
    return pd.read_parquet(_require(config.SCREENER_FILE))


@functools.lru_cache(maxsize=1)
def get_catalog() -> dict[str, indicators.Indicator]:
    meta = get_meta()
    return indicators.build_catalog(meta["fundamental_columns"], meta["price_columns"])


@functools.lru_cache(maxsize=1)
def get_indicator_options() -> list[dict[str, str]]:
    return indicators.dropdown_options(get_catalog())


# --- filter helpers --------------------------------------------------------


@functools.lru_cache(maxsize=1)
def get_sector_options() -> list[dict[str, str]]:
    stocks = get_stocks()
    values = sorted(stocks[config.SECTOR_COL].dropna().unique())
    return [{"label": v, "value": v} for v in values]


def filter_universe(
    sectors: list[str] | None,
    industries: list[str] | None,
    tickers: list[str] | None = None,
    active_only: bool = False,
) -> pd.DataFrame:
    """Narrow the ticker universe by the shared dropdown filters.

    The three dropdowns cascade: a sector limits the industries on offer, and
    either limits the tickers. An empty selection means "no restriction".
    """
    stocks = get_stocks()
    mask = pd.Series(True, index=stocks.index)

    if active_only:
        mask &= stocks["is_active"]
    if sectors:
        mask &= stocks[config.SECTOR_COL].isin(sectors)
    if industries:
        mask &= stocks[config.INDUSTRY_COL].isin(industries)
    if tickers:
        mask &= stocks["ticker"].isin(tickers)

    return stocks[mask]


# --- long history ----------------------------------------------------------


@functools.lru_cache(maxsize=1024)
def _read_ticker_history(source: str, ticker: str, columns: tuple[str, ...]) -> pd.DataFrame:
    """Read one ticker's history for a few columns, straight from the raw file."""
    path = config.RAW_PRICES if source == indicators.SOURCE_PRICE else config.RAW_FUNDAMENTALS
    table = pq.read_table(
        _require(path),
        columns=["date", *columns],
        filters=[("ticker", "==", ticker)],
    )
    frame = table.to_pandas()
    frame.insert(0, "ticker", ticker)
    return frame.sort_values("date", ignore_index=True)


def get_history(
    tickers: list[str] | tuple[str, ...],
    columns: list[str] | tuple[str, ...],
    source: str = indicators.SOURCE_PRICE,
) -> pd.DataFrame:
    """Long-format history (ticker, date, <columns>) for the given tickers.

    Caching is per ticker rather than per selection, so adding one ticker to an
    existing chart only costs one new read.
    """
    if not tickers:
        return pd.DataFrame(columns=["ticker", "date", *columns])

    columns = tuple(columns)
    frames = [_read_ticker_history(source, t, columns) for t in tickers]
    return pd.concat(frames, ignore_index=True)


def source_of(column: str) -> str:
    indicator = get_catalog().get(column)
    return indicator.source if indicator else indicators.SOURCE_PRICE


# --- cross sections --------------------------------------------------------
# The pages above ask for a few tickers across all dates. The heatmap and the
# distribution page ask the opposite question - every ticker on one date - which
# the ticker-sorted file cannot prune for. Reading a handful of columns is still
# only a few tenths of a second, and each answer is cached.


@functools.lru_cache(maxsize=1)
def get_month_grid() -> pd.DatetimeIndex:
    """One step per month across all history - the scale behind the range sliders.

    A slider over 10,000 trading days would be unusable; months give a handle
    that moves in meaningful increments and still reaches any period.
    """
    meta = get_meta()
    start = pd.Timestamp(meta["price_date_min"]).replace(day=1)
    end = pd.Timestamp(meta["price_date_max"])
    return pd.date_range(start, end, freq="MS")


@functools.lru_cache(maxsize=1)
def get_trading_dates() -> pd.DatetimeIndex:
    """Every date that appears in the price file, ascending."""
    dates = pq.read_table(_require(config.RAW_PRICES), columns=["date"]).to_pandas()["date"]
    return pd.DatetimeIndex(np.sort(dates.unique()))


def snap_to_trading_date(value, *, latest_if_missing: bool = True) -> pd.Timestamp:
    """Nearest trading date at or before `value`.

    The date pickers allow any calendar day, so a weekend or holiday has to fall
    back to the session before it rather than returning nothing.
    """
    dates = get_trading_dates()
    if value is None:
        return dates[-1] if latest_if_missing else dates[0]

    stamp = pd.Timestamp(value).normalize()
    position = dates.searchsorted(stamp, side="right") - 1
    if position < 0:
        return dates[0]
    return dates[position]


@functools.lru_cache(maxsize=64)
def _price_cross_section(dates: tuple[str, ...], columns: tuple[str, ...]) -> pd.DataFrame:
    stamps = [pd.Timestamp(d) for d in dates]
    table = pq.read_table(
        _require(config.RAW_PRICES),
        columns=["date", "ticker", *columns],
        filters=[("date", "in", stamps)],
    )
    return table.to_pandas()


@functools.lru_cache(maxsize=64)
def _fundamental_cross_section(date_iso: str, columns: tuple[str, ...]) -> pd.DataFrame:
    """Each ticker's most recent quarter as of `date_iso`.

    Fundamentals are quarterly, so "the value on 12 March" means the last
    quarter that had been reported by then.
    """
    table = pq.read_table(
        _require(config.RAW_FUNDAMENTALS),
        columns=["date", "ticker", *columns],
        filters=[("date", "<=", pd.Timestamp(date_iso))],
    )
    frame = table.to_pandas().sort_values("date")
    return frame.groupby("ticker", as_index=False).tail(1)


def get_cross_section(date, columns: list[str] | tuple[str, ...]) -> pd.DataFrame:
    """One row per ticker with the requested indicators as of `date`.

    Sector and industry come along, so callers can filter without a second join.
    """
    date_iso = str(pd.Timestamp(date).date())
    catalog = get_catalog()

    price_cols = tuple(c for c in columns if catalog[c].source == indicators.SOURCE_PRICE)
    fundamental_cols = tuple(
        c for c in columns if catalog[c].source == indicators.SOURCE_FUNDAMENTAL
    )

    frame = get_stocks()[
        ["ticker", config.SECTOR_COL, config.INDUSTRY_COL, "is_active"]
    ].copy()

    if price_cols:
        prices = _price_cross_section((date_iso,), price_cols).drop(columns=["date"])
        frame = frame.merge(prices, on="ticker", how="left")
    if fundamental_cols:
        fundamentals = _fundamental_cross_section(date_iso, fundamental_cols).drop(
            columns=["date"]
        )
        frame = frame.merge(fundamentals, on="ticker", how="left")

    return frame


@functools.lru_cache(maxsize=32)
def get_price_extremes(start, end) -> pd.DataFrame:
    """Highest, lowest and last close per ticker across a whole window.

    Different shape of question from `get_price_change`, which only needs the
    two end dates: this has to see every session in between, so it reads the
    range rather than two slices of it. The aggregate is cached, not the rows.

    "Last" is the newest session the ticker actually traded, which for a name
    that stopped part-way through is earlier than the window's end.
    """
    start_stamp, end_stamp = pd.Timestamp(start), pd.Timestamp(end)
    table = pq.read_table(
        _require(config.RAW_PRICES),
        columns=["date", "ticker", "close", "MarketCap"],
        filters=[("date", ">=", start_stamp), ("date", "<=", end_stamp)],
    )
    frame = table.to_pandas()
    frame = frame.dropna(subset=["close"])
    frame = frame[frame["close"] > 0]
    if frame.empty:
        return pd.DataFrame()

    closes = frame.groupby("ticker", sort=False)["close"]
    extremes = pd.DataFrame({"high": closes.max(), "low": closes.min()}).reset_index()

    # Take the newest row per ticker by date rather than by position, so this
    # does not silently depend on the file's sort order.
    newest = frame.loc[frame.groupby("ticker")["date"].idxmax()]
    newest = newest[["ticker", "date", "close", "MarketCap"]].rename(
        columns={"date": "last_date", "close": "last"}
    )

    merged = extremes.merge(newest, on="ticker", how="inner")
    merged = merged[merged["MarketCap"] > 0]

    stocks = get_stocks()[["ticker", config.SECTOR_COL, config.INDUSTRY_COL]]
    return merged.merge(stocks, on="ticker", how="left").reset_index(drop=True)


def get_price_change(start, end) -> pd.DataFrame:
    """Percent price change between two dates, with market cap at the end date.

    Only tickers priced on *both* dates are returned - a change needs two ends.
    """
    start_iso = str(pd.Timestamp(start).date())
    end_iso = str(pd.Timestamp(end).date())

    raw = _price_cross_section(tuple(sorted({start_iso, end_iso})), ("close", "MarketCap"))
    closes = raw.pivot(index="ticker", columns="date", values="close")

    start_stamp, end_stamp = pd.Timestamp(start_iso), pd.Timestamp(end_iso)
    if start_stamp not in closes.columns or end_stamp not in closes.columns:
        return pd.DataFrame()

    frame = pd.DataFrame(
        {
            "close_start": closes[start_stamp],
            "close_end": closes[end_stamp],
        }
    ).dropna()
    frame = frame[frame["close_start"] > 0]
    frame["change_pct"] = (frame["close_end"] / frame["close_start"] - 1) * 100

    caps = raw[raw["date"] == end_stamp].set_index("ticker")["MarketCap"]
    frame["MarketCap"] = caps
    frame = frame[frame["MarketCap"] > 0].reset_index()

    stocks = get_stocks()[["ticker", config.SECTOR_COL, config.INDUSTRY_COL]]
    return frame.merge(stocks, on="ticker", how="left")
