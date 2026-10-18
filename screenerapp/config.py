"""Paths and shared constants.

The data itself comes from the `features` package, which finds its own build
(see its README). This project only keeps the tables it derives for its pages.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Built by screenerapp/cache.py from the package at start-up, once per features build.
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
SNAPSHOT_FILE = CACHE_DIR / "snapshot.parquet"
TRADING_DATES_FILE = CACHE_DIR / "trading_dates.parquet"
BUILD_ID_FILE = CACHE_DIR / "build_id.txt"

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
