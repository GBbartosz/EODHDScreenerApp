"""The indicator catalog.

Every numeric column in the two parquet files becomes an ``Indicator``: which
file it lives in, which group it belongs to in the dropdowns, and how it should
be formatted. Pages read from this catalog rather than hard-coding column names,
so a new column in a data drop shows up everywhere automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config

# --- formatting ------------------------------------------------------------
# Money columns are reported in millions; margins, changes and CAGRs are stored
# as fractions (0.4667 means 46.67%); a handful of columns are counters or flags.

MONEY_BASES = (
    "totalRevenue",
    "grossProfit",
    "operatingIncome",
    "ebitda",
    "ebit",
    "netIncome",
    "researchDevelopment",
    "capitalExpenditures",
    "totalCashflowsFromInvestingActivities",
    "totalCashFromFinancingActivities",
    "totalCashFromOperatingActivities",
    "freeCashFlow",
    "commonStockSharesOutstanding",
    "netDebt",
    "cashAndShortTermInvestments",
    "totalDebt",
)

# Exact column names that hold a money amount - the base itself and its TTM
# variant. Anything longer (a _chg_ or _CAGR_ of these) is a rate, not an amount.
MONEY_COLUMNS = frozenset(
    list(MONEY_BASES)
    + [f"TTM_{base}" for base in MONEY_BASES]
    + ["MarketCap", "EnterpriseValue"]
)

COUNTER_MARKERS = ("_consec_growth", "_sign_state")
RATE_MARKERS = ("Margin", "_chg", "_CAGR", "_delta", "_pct")

FMT_MONEY = "money"
FMT_PERCENT = "percent"
FMT_RATIO = "ratio"
FMT_INT = "int"

SOURCE_FUNDAMENTAL = "fundamental"
SOURCE_PRICE = "price"


@dataclass(frozen=True)
class Indicator:
    column: str
    category: str
    source: str
    fmt: str

    @property
    def option_label(self) -> str:
        """Label used in dropdowns - keeps the exact column name searchable."""
        return f"{self.category} · {self.column}"


def _fmt_for(column: str) -> str:
    if any(marker in column for marker in COUNTER_MARKERS) or column == "gspc_bull":
        return FMT_INT
    if column in MONEY_COLUMNS:
        return FMT_MONEY
    if any(marker in column for marker in RATE_MARKERS):
        return FMT_PERCENT
    return FMT_RATIO


def _fundamental_category(column: str) -> str:
    if "Margin" in column:
        return "Margins"
    if "_CAGR_" in column:
        return "Growth (CAGR)"
    if any(m in column for m in ("_chg_", "_delta_", "_consec_growth", "_sign_state")):
        return "Growth & Change"
    if column.startswith("TTM_"):
        return "TTM Levels"

    base = column
    if base in ("commonStockSharesOutstanding", "netDebt", "cashAndShortTermInvestments", "totalDebt"):
        return "Balance Sheet"
    if base in (
        "capitalExpenditures",
        "totalCashflowsFromInvestingActivities",
        "totalCashFromFinancingActivities",
        "totalCashFromOperatingActivities",
        "freeCashFlow",
    ):
        return "Cash Flow"
    if base in (
        "totalRevenue",
        "grossProfit",
        "operatingIncome",
        "ebitda",
        "ebit",
        "netIncome",
        "researchDevelopment",
    ):
        return "Income Statement"
    return "Other Fundamentals"


def _price_category(column: str) -> str:
    if "gspc_adj" in column:
        return "Market-Adjusted"
    if column.startswith("gspc"):
        return "Market (S&P 500)"
    if column == "close" or column.startswith("close_"):
        return "Price"
    if column.startswith(("PSG_", "PEG_", "PFCFG_", "EVrevenueG", "EVebitdaG", "EVebitG")):
        return "Growth-Adjusted Valuation"
    if column in ("PS", "PE", "PFCF", "PRR"):
        return "Valuation"
    if column in ("MarketCap", "EnterpriseValue"):
        return "Size"
    if column.startswith("EV"):
        return "Enterprise Value"
    return "Other Price"


# Dropdown ordering - categories a screener reaches for first come first.
CATEGORY_ORDER = (
    "Price",
    "Valuation",
    "Size",
    "Growth-Adjusted Valuation",
    "Enterprise Value",
    "Income Statement",
    "TTM Levels",
    "Margins",
    "Growth & Change",
    "Growth (CAGR)",
    "Cash Flow",
    "Balance Sheet",
    "Market-Adjusted",
    "Market (S&P 500)",
    "Other Fundamentals",
    "Other Price",
)


def build_catalog(
    fundamental_columns: list[str], price_columns: list[str]
) -> dict[str, Indicator]:
    """Map every usable column to an Indicator.

    Price columns win ties: the screener shows one row per ticker as of the most
    recent trading day, so a column present in both files is taken from prices.
    """
    catalog: dict[str, Indicator] = {}

    for column in fundamental_columns:
        if column in config.KEY_COLUMNS:
            continue
        catalog[column] = Indicator(
            column=column,
            category=_fundamental_category(column),
            source=SOURCE_FUNDAMENTAL,
            fmt=_fmt_for(column),
        )

    for column in price_columns:
        if column in config.KEY_COLUMNS:
            continue
        catalog[column] = Indicator(
            column=column,
            category=_price_category(column),
            source=SOURCE_PRICE,
            fmt=_fmt_for(column),
        )

    return catalog


def sort_key(indicator: Indicator) -> tuple[int, str]:
    try:
        rank = CATEGORY_ORDER.index(indicator.category)
    except ValueError:
        rank = len(CATEGORY_ORDER)
    return rank, indicator.column.lower()


def dropdown_options(catalog: dict[str, Indicator]) -> list[dict[str, str]]:
    """Options for any indicator dropdown, grouped by category via the label."""
    return [
        {"label": ind.option_label, "value": ind.column}
        for ind in sorted(catalog.values(), key=sort_key)
    ]


def table_format(indicator: Indicator):
    """Dash DataTable format spec, so columns stay numeric (and sortable)."""
    from dash.dash_table.Format import Format, Group, Scheme

    if indicator.fmt == FMT_MONEY:
        return Format(precision=0, scheme=Scheme.fixed, group=Group.yes)
    if indicator.fmt == FMT_PERCENT:
        return Format(precision=2, scheme=Scheme.percentage)
    if indicator.fmt == FMT_INT:
        return Format(precision=0, scheme=Scheme.fixed)
    return Format(precision=2, scheme=Scheme.fixed)
