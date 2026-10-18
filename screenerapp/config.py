"""Paths and shared constants.

Everything that knows *where* data lives is here, so moving or renaming a data
drop only requires editing this file.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"

# Raw drop - replaced by hand a few times a year.
RAW_PRICES = DATA_DIR / "prices_raw.parquet"
RAW_FUNDAMENTALS = DATA_DIR / "fundamentals_raw.parquet"
RAW_TICKERS = DATA_DIR / "tickers.parquet"
RAW_FX = DATA_DIR / "fx_rates.parquet"
RAW_INDEX = DATA_DIR / "index_prices.parquet"  # optional - GSPC for the gspc_* columns

# Built by building_features.py.
FUNDAMENTAL_FEATURES = PROCESSED_DIR / "fundamental_features.parquet"
PRICE_FEATURES = PROCESSED_DIR / "price_features.parquet"

# Built by prepare_data.py.
SCREENER_FILE = PROCESSED_DIR / "screener_latest.parquet"
STOCKS_FILE = PROCESSED_DIR / "stocks.parquet"
TRADING_DATES_FILE = PROCESSED_DIR / "trading_dates.parquet"
META_FILE = PROCESSED_DIR / "meta.json"

# Columns that identify a row rather than describe a company. Never offered as
# indicators.
KEY_COLUMNS = (
    "ticker",
    "date",
    "filing_date",
    "earnings_report_date",
    "available_date",
    "yq",
    "quarter",
    "fund_date",
    "fund_stale",
    "source",
)

# Price features that combine the price with fundamentals. They are blank on days
# when the quarter behind them may already have been superseded by a newer report
# that is not in the data (`fund_stale`) - typically some weeks after the
# fundamentals download, while yfinance prices carry on. MarketCap is not in the
# list: a share count drifts slowly, so it stays usable for sizing.
VALUATION_COLUMNS = (
    "PS",
    "PE",
    "PFCF",
    "PRR",
    "PSG_4q",
    "PSG_20q",
    "PSG_40q",
    "PEG_4q",
    "PEG_20q",
    "PEG_40q",
    "PFCFG_4q",
    "PFCFG_20q",
    "PFCFG_40q",
    "EnterpriseValue",
    "EVrevenue",
    "EVebitda",
    "EVebit",
    "EVrevenueG_4q",
    "EVrevenueG_20q",
    "EVrevenueG_40q",
    "EVebitdaG_chg_4q",
    "EVebitdaG_CAGR_20q",
    "EVebitdaG_CAGR_40q",
    "EVebitG_chg_4q",
    "EVebitG_CAGR_20q",
    "EVebitG_CAGR_40q",
)

# Columns pinned to the left of the screener table, in this order.
LEADING_COLUMNS = ("ticker", "fundamental_date", "valuation_date", "date")

LEADING_COLUMN_LABELS = {
    "ticker": "ticker",
    "fundamental_date": "fundamental date",
    "valuation_date": "valuation date",
    "date": "date",
}

# A ticker counts as active if its most recent price is within this many days
# of the newest price in the whole dataset. Catches names that stopped trading
# (acquired, delisted) without being thrown off by a ticker that simply missed
# the final session or two.
ACTIVE_WINDOW_DAYS = 30

# Classification scheme driving the sector/industry dropdowns.
SECTOR_COL = "Sector"
INDUSTRY_COL = "Industry"

# Shown on the screener before you pick your own indicators.
DEFAULT_SCREENER_INDICATORS = (
    "close",
    "MarketCap",
    "PE",
    "PS",
    "TTM_totalRevenue",
    "TTM_totalRevenue_chg_4q",
    "grossMargin",
    "netMargin",
)
