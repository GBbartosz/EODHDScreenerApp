"""Paths and shared constants.

Everything that knows *where* data lives is here, so moving or renaming a data
drop only requires editing this file.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"

# Raw drops - replaced by hand a few times a year.
RAW_FUNDAMENTALS = DATA_DIR / "pe_model_fundamental_features.parquet"
RAW_PRICES = DATA_DIR / "pe_model_price_features.parquet"
RAW_STOCKS = DATA_DIR / "stocks.csv"

# Built by prepare_data.py.
SCREENER_FILE = PROCESSED_DIR / "screener_latest.parquet"
STOCKS_FILE = PROCESSED_DIR / "stocks.parquet"
META_FILE = PROCESSED_DIR / "meta.json"

# Columns that identify a row rather than describe a company. Never offered as
# indicators.
KEY_COLUMNS = ("ticker", "date", "filing_date", "yq", "quarter")

# Columns pinned to the left of the screener table, in this order.
LEADING_COLUMNS = ("ticker", "fundamental_date", "date")

LEADING_COLUMN_LABELS = {
    "ticker": "ticker",
    "fundamental_date": "fundamental date",
    "date": "date",
}

# A ticker counts as active if its most recent price is within this many days
# of the newest price in the whole dataset. Catches names that stopped trading
# (acquired, delisted) without being thrown off by a ticker that simply missed
# the final session.
#
# Deliberately a month rather than a week: in the current drop, ~94 tickers
# (mostly alphabetically late - SO, T, SYK, SPGI) stop at 2026-01-30 while the
# rest run to 2026-02-13, which looks like the price extraction being cut short
# rather than 94 delistings. A 30-day window keeps those names in the screener.
# Tighten this once a drop lands with an even end date across the universe.
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
