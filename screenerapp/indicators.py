"""The indicator catalog: every column a page can offer, built from the features package.

The package describes each column (unit, category, description); this module only
decides which ones the app offers and how to show them. Two sources:

* price - daily rows of the package's screener view (its PE, PFCF, ... with the app's
  rules: NaN for a non-positive denominator, valuation ratios blank when stale).
* fundamental - quarterly rows of `fundamentals_quarterly`. Leverage and returns on
  capital (ROE, ROA, ...) come from the view's own definitions, applied here to the
  quarterly rows, so they are NaN for a denominator up to 1 M whatever the frequency.
"""

from __future__ import annotations

from dataclasses import dataclass

import features
from features.views import screener

QUARTERLY = "fundamentals_quarterly."

# The view's columns computed only from quarterly inputs: shown as fundamentals.
QUARTERLY_RULES = {
    c.name: c for c in screener.COLUMNS if all(i.startswith(QUARTERLY) for i in c.inputs)
}

NUMERIC_DTYPES = frozenset({"float32", "float64", "int16", "int32", "int64"})
HIDDEN = frozenset({"fx_per_usd", "quarter"})  # numeric, but not something to screen on

FMT_MONEY = "money"
FMT_PERCENT = "percent"
FMT_RATIO = "ratio"
FMT_INT = "int"
FMT_BY_UNIT = {
    "money_mn_local": FMT_MONEY,
    "money_mn_usd": FMT_MONEY,
    "shares_mn": FMT_MONEY,
    "fraction": FMT_PERCENT,
    "count": FMT_INT,
    "enum": FMT_INT,
}  # anything else (ratio, price_local, points) is a plain number

SOURCE_FUNDAMENTAL = "fundamental"
SOURCE_PRICE = "price"

# Dropdown ordering - categories a screener reaches for first come first.
CATEGORY_ORDER = (
    "Price",
    "Returns",
    "Valuation",
    "Size",
    "Growth-Adjusted Valuation",
    "Enterprise Value",
    "Income Statement",
    "TTM Levels",
    "Margins",
    "Returns & Leverage",
    "Growth & Change",
    "Growth (CAGR)",
    "Cash Flow",
    "Balance Sheet",
    "Market-Relative",
    "Other",
)


@dataclass(frozen=True)
class Indicator:
    column: str
    category: str
    source: str
    unit: str
    description: str
    is_valuation: bool

    @property
    def fmt(self) -> str:
        return FMT_BY_UNIT.get(self.unit, FMT_RATIO)

    @property
    def option_label(self) -> str:
        """Label used in dropdowns - keeps the exact column name searchable."""
        return f"{self.category} · {self.column}"


def not_offered_reason(column: str, dtype: str, is_forward_looking: bool) -> str | None:
    """Why a column is kept out of the indicator dropdowns, or None if it is offered.

    Numbers only, and not the duplicates the app shows under another name:
    *_signed keep a negative denominator's sign (the app shows NaN there), *_local are
    MarketCap / EV in the trading currency (the app compares in USD). Forward-looking
    columns use the future, so they never belong in a screen."""
    if dtype not in NUMERIC_DTYPES:
        return "not numeric"
    if is_forward_looking:
        return "forward-looking"
    if column in HIDDEN:
        return "not a screening value"
    if column.endswith("_signed"):
        return "signed duplicate"
    if column.endswith("_local"):
        return "local-currency duplicate"
    return None


def _offered(row) -> bool:
    return not_offered_reason(row.column, row.dtype, row.is_forward_looking) is None


def build_catalog() -> dict[str, Indicator]:
    canonical = features.get_catalog()
    dtypes = canonical.set_index(["table", "column"])["dtype"]
    view = screener.catalog()
    # Columns the view computes itself (PE, ROE, ...) are float ratios.
    view["dtype"] = [
        "float32" if src == "view" else dtypes[("price_daily", col)]
        for col, src in zip(view["column"], view["source"])
    ]

    catalog: dict[str, Indicator] = {}
    quarterly = canonical[canonical["table"] == "fundamentals_quarterly"]
    for row in quarterly[~quarterly["is_key"]].itertuples():
        if _offered(row):
            catalog[row.column] = Indicator(
                row.column, row.category, SOURCE_FUNDAMENTAL, row.unit, row.description, False
            )
    for row in view.itertuples():
        if not _offered(row):
            continue
        # A quarterly rule replaces the canonical column of the same name (ROA,
        # interest_coverage) - one name, one number.
        source = SOURCE_FUNDAMENTAL if row.column in QUARTERLY_RULES else SOURCE_PRICE
        catalog[row.column] = Indicator(
            row.column, row.category, source, row.unit, row.description, bool(row.is_valuation)
        )
    return catalog


# --- quarterly rows --------------------------------------------------------


def quarterly_inputs(columns) -> list[str]:
    """Canonical `fundamentals_quarterly` columns to read for these fundamental columns."""
    names = []
    for column in columns:
        rule = QUARTERLY_RULES.get(column)
        names += [i.removeprefix(QUARTERLY) for i in rule.inputs] if rule else [column]
    return list(dict.fromkeys(names))


def apply_quarterly_rules(frame, columns):
    """`frame` (canonical quarterly inputs under their bare names) with the app's
    leverage and return ratios computed in place of the canonical ones."""
    values = {c: QUARTERLY_RULES[c].compute(frame) for c in columns if c in QUARTERLY_RULES}
    return frame.assign(**values)


# --- presentation ----------------------------------------------------------


def sort_key(indicator: Indicator) -> tuple[int, str]:
    try:
        rank = CATEGORY_ORDER.index(indicator.category)
    except ValueError:
        rank = len(CATEGORY_ORDER)
    return rank, indicator.column.lower()


def dropdown_options(catalog: dict[str, Indicator]) -> list[dict]:
    """Options for any indicator dropdown, grouped by category via the label; the
    package's description is the hover text."""
    return [
        {"label": ind.option_label, "value": ind.column, "title": ind.description}
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
