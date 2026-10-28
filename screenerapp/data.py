"""Data access layer, on top of the `features` package.

Two shapes of data, loaded two ways:

* Small, always-needed tables - the screener snapshot and the session calendar
  (built by ``cache.py`` once per features build), the ticker universe and the
  catalog - are held in memory.
* Long history and cross-sections are read from the package on demand, a few
  columns at a time, and cached: one ticker's history costs a few hundredths of
  a second, every ticker on one date about a tenth.

Price columns come through the package's screener view, so they carry the app's
rules (P/E NaN for a loss, valuation ratios blank when stale). Fundamental
columns are quarterly rows (see indicators.py for the leverage and return ratios).

Everything returned by a cached function is shared, so treat it as read-only:
filter or copy before mutating. The caches live as long as the process: restart
the app after a new features build.
"""

from __future__ import annotations

import functools

import numpy as np
import pandas as pd

import features
from features.treatments import fill_category
from features.views import screener

from . import config, indicators

UNIVERSE_COLUMNS = ["name", "exchange", "currency", config.SECTOR_COL, config.INDUSTRY_COL,
                    "first_price_date", "last_price_date", "has_fundamentals"]


@functools.lru_cache(maxsize=1)
def get_meta() -> dict:
    """The package's manifest, plus the app's own active-ticker counts."""
    meta = dict(features.get_manifest())
    cutoff = pd.Timestamp(meta["price_date_max"]) - pd.Timedelta(days=config.ACTIVE_WINDOW_DAYS)
    meta["active_cutoff"] = str(cutoff.date())
    meta["n_active"] = int(get_stocks()["is_active"].sum())
    return meta


@functools.lru_cache(maxsize=1)
def get_stocks() -> pd.DataFrame:
    """One row per ticker: sector, industry, currency, and whether it still trades."""
    stocks = features.read_table("universe", UNIVERSE_COLUMNS)
    for column in (config.SECTOR_COL, config.INDUSTRY_COL):
        stocks[column] = fill_category(stocks[column])
    newest = pd.Timestamp(features.get_manifest()["price_date_max"])
    stocks["is_active"] = stocks["last_price_date"] >= newest - pd.Timedelta(days=config.ACTIVE_WINDOW_DAYS)
    return stocks.sort_values("ticker", ignore_index=True)


@functools.lru_cache(maxsize=1)
def get_snapshot() -> pd.DataFrame:
    """Latest row per ticker in the trading currency (see cache.py)."""
    return pd.read_parquet(config.SNAPSHOT_FILE)


@functools.lru_cache(maxsize=1)
def get_screener() -> pd.DataFrame:
    """The snapshot with amounts in USD, so tickers rank against each other."""
    return to_usd(get_snapshot())


@functools.lru_cache(maxsize=1)
def get_catalog() -> dict[str, indicators.Indicator]:
    return indicators.build_catalog()


@functools.lru_cache(maxsize=1)
def get_indicator_options() -> list[dict]:
    return indicators.dropdown_options(get_catalog())


def to_usd(frame: pd.DataFrame) -> pd.DataFrame:
    """Amounts in the trading currency divided by the day's `fx_per_usd`.

    Fundamentals are in the currency the ticker trades in; MarketCap and
    EnterpriseValue are already USD. Ratios and per-share values are left alone.
    """
    catalog = get_catalog()
    local = [c for c in frame.columns if c in catalog and catalog[c].unit == "money_mn_local"]
    return frame.assign(**{c: frame[c] / frame["fx_per_usd"] for c in local})


def source_of(column: str) -> str:
    indicator = get_catalog().get(column)
    return indicator.source if indicator else indicators.SOURCE_PRICE


# --- filter helpers --------------------------------------------------------


@functools.lru_cache(maxsize=1)
def get_sector_options() -> list[dict[str, str]]:
    values = sorted(get_stocks()[config.SECTOR_COL].unique())
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


def _quarterly(columns, tickers=None) -> pd.DataFrame:
    """Quarterly rows (ticker, date = period end, <columns>), app rules applied."""
    frame = features.read_table("fundamentals_quarterly", indicators.quarterly_inputs(columns), tickers=tickers)
    return indicators.apply_quarterly_rules(frame, columns)[["ticker", "date", *columns]]


def _point_in_time(frame: pd.DataFrame) -> pd.DataFrame:
    """Quarterly rows re-dated to the day each one came into force.

    `available_date` is the first day the quarter's numbers were public - the same
    key the package's point-in-time join uses for the cross-sections. The raw
    `filing_date` is not used: EODHD fills it with placeholders (on or before the
    period end for about a fifth of quarters), which would leak numbers early.

    A quarter released late, after a newer one was already public, never comes
    into force; of quarters released on the same day only the newest does. So
    `date` becomes the release day and `period_end` keeps the quarter it reports.
    """
    frame = frame.sort_values(["ticker", "available_date", "date"])
    newest_before = frame.groupby("ticker")["date"].cummax().groupby(frame["ticker"]).shift()
    frame = frame[newest_before.isna() | (frame["date"] > newest_before)]
    frame = frame.drop_duplicates(["ticker", "available_date"], keep="last")
    return frame.rename(columns={"date": "period_end", "available_date": "date"}).reset_index(drop=True)


@functools.lru_cache(maxsize=1024)
def _read_ticker_history(
    source: str, ticker: str, columns: tuple[str, ...], point_in_time: bool = False
) -> pd.DataFrame:
    if source == indicators.SOURCE_PRICE:
        return screener.load(list(columns), tickers=[ticker])
    keys = ["ticker", "date", "period_end"] if point_in_time else ["ticker", "date"]
    stocks = get_stocks()
    if not stocks.loc[stocks["ticker"] == ticker, "has_fundamentals"].any():
        return pd.DataFrame(columns=[*keys, *columns])
    if not point_in_time:
        return _quarterly(columns, tickers=[ticker])
    frame = features.read_table(
        "fundamentals_quarterly",
        [*indicators.quarterly_inputs(columns), "available_date"],
        tickers=[ticker],
    )
    frame = indicators.apply_quarterly_rules(frame, columns)
    return _point_in_time(frame[["ticker", "date", "available_date", *columns]])[[*keys, *columns]]


def get_history(
    tickers: list[str] | tuple[str, ...],
    columns: list[str] | tuple[str, ...],
    source: str = indicators.SOURCE_PRICE,
    point_in_time: bool = False,
) -> pd.DataFrame:
    """Long-format history (ticker, date, <columns>) for the given tickers.

    `source` price gives one row per trading day, fundamental one per quarter.
    A quarter is dated by its period end, or with `point_in_time` by the day its
    numbers became public, with its period end kept in `period_end` (see
    _point_in_time). Caching is per ticker rather than per selection, so adding
    one ticker to an existing chart only costs one new read.
    """
    if not tickers:
        keys = ["ticker", "date", "period_end"] if point_in_time else ["ticker", "date"]
        return pd.DataFrame(columns=[*keys, *columns])

    columns = tuple(columns)
    frames = [_read_ticker_history(source, t, columns, point_in_time) for t in tickers]
    return pd.concat(frames, ignore_index=True)


@functools.lru_cache(maxsize=64)
def get_price_panel(tickers: tuple[str, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Wide (date x ticker) total-return close and market cap, both in USD.

    For the market page's group indexes, so tickers in different currencies add
    up. Each ticker is carried forward over gaps inside its own life (first to
    last priced day) and left blank outside it: a missed session is then not
    mistaken for a delisting. A non-USD ticker's life starts with its first
    exchange rate.

    The dates run on through the US calendar, so a group whose last stock stopped
    trading years ago still shows it leaving rather than being held to the end.
    """
    frame = features.read_table("price_daily", ["close", "MarketCap", "fx_per_usd"], tickers=list(tickers))
    frame["close_usd"] = frame["close"] / frame["fx_per_usd"]
    prices = frame.pivot(index="date", columns="ticker", values="close_usd")
    prices = prices.reindex(prices.index.union(get_trading_dates()))
    caps = frame.pivot(index="date", columns="ticker", values="MarketCap").reindex_like(prices)
    life = prices.ffill().notna() & prices.bfill().notna()
    return prices.ffill().where(life), caps.ffill().where(life)


# --- cross sections --------------------------------------------------------
# The pages above ask for a few tickers across all dates. The heatmap and the
# distribution page ask the opposite question - every ticker on one date. The
# package's price table is sorted by ticker, so a date cannot prune it; reading a
# handful of columns is still about a tenth of a second, and each answer is cached.


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
    """Every US session, ascending (see cache.trading_dates)."""
    dates = pd.read_parquet(config.TRADING_DATES_FILE)["date"]
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
def _price_cross_section(date_iso: str, columns: tuple[str, ...]) -> pd.DataFrame:
    return screener.load([*columns, "fx_per_usd"], start=date_iso, end=date_iso).drop(columns="date")


@functools.lru_cache(maxsize=64)
def _fundamental_cross_section(date_iso: str, columns: tuple[str, ...]) -> pd.DataFrame:
    """The quarter in force on `date_iso` for every ticker priced that day.

    The package's point-in-time join decides which quarter that is: the newest one
    whose numbers were public by then (its release, not its period end).
    """
    refs = [indicators.QUARTERLY + c for c in indicators.quarterly_inputs(columns)]
    frame = features.read_table("price_daily", refs, start=date_iso, end=date_iso)
    return indicators.apply_quarterly_rules(frame, columns)[["ticker", *columns]]


def get_cross_section(date, columns: list[str] | tuple[str, ...]) -> pd.DataFrame:
    """One row per ticker priced on `date`, with the requested indicators as of then.

    Amounts are in USD. Sector and industry come along, so callers can filter
    without a second join.
    """
    date_iso = str(pd.Timestamp(date).date())
    catalog = get_catalog()
    columns = tuple(dict.fromkeys(columns))  # both dropdowns may pick the same one
    fundamental = tuple(c for c in columns if catalog[c].source == indicators.SOURCE_FUNDAMENTAL)
    price = tuple(c for c in columns if c not in fundamental)

    frame = _price_cross_section(date_iso, price)
    if fundamental:
        frame = frame.merge(_fundamental_cross_section(date_iso, fundamental), on="ticker")
    stocks = get_stocks()[["ticker", config.SECTOR_COL, config.INDUSTRY_COL, "is_active"]]
    return stocks.merge(to_usd(frame), on="ticker")


@functools.lru_cache(maxsize=32)
def get_price_extremes(start, end) -> pd.DataFrame:
    """Highest, lowest and last close per ticker across a whole window, with dates.

    Different shape of question from `get_price_change`, which only needs the
    two end dates: this has to see every session in between, so it reads the
    range rather than two slices of it. The aggregate is cached, not the rows.

    "Last" is the newest session the ticker actually traded, which for a name
    that stopped part-way through is earlier than the window's end.
    """
    frame = features.read_table("price_daily", ["close", "MarketCap"], start=start, end=end)
    frame = frame[frame["close"] > 0]
    if frame.empty:
        return pd.DataFrame()

    closes = frame.groupby("ticker")["close"]
    extremes = pd.DataFrame(
        {
            "high": closes.max(),
            "high_date": frame.loc[closes.idxmax(), "date"].to_numpy(),
            "low": closes.min(),
            "low_date": frame.loc[closes.idxmin(), "date"].to_numpy(),
        }
    ).reset_index()

    newest = frame.loc[frame.groupby("ticker")["date"].idxmax()]
    newest = newest[["ticker", "date", "close", "MarketCap"]].rename(
        columns={"date": "last_date", "close": "last"}
    )

    merged = extremes.merge(newest, on="ticker")
    merged = merged[merged["MarketCap"] > 0]

    stocks = get_stocks()[["ticker", config.SECTOR_COL, config.INDUSTRY_COL]]
    return merged.merge(stocks, on="ticker", how="left").reset_index(drop=True)


def get_price_change(start, end) -> pd.DataFrame:
    """Percent price change between two dates, with market cap at the end date.

    Only tickers priced on *both* dates are returned - a change needs two ends.
    """
    columns = ("close", "MarketCap")
    first = _price_cross_section(str(pd.Timestamp(start).date()), columns)
    last = _price_cross_section(str(pd.Timestamp(end).date()), columns)

    frame = first[["ticker", "close"]].merge(last, on="ticker", suffixes=("_start", "_end"))
    frame = frame[(frame["close_start"] > 0) & (frame["MarketCap"] > 0)].copy()
    frame["change_pct"] = (frame["close_end"] / frame["close_start"] - 1) * 100

    stocks = get_stocks()[["ticker", config.SECTOR_COL, config.INDUSTRY_COL]]
    return frame.merge(stocks, on="ticker", how="left").reset_index(drop=True)
