"""The feature documentation table: every column the features package defines, in one frame.

Two layers, one row per column:

* canonical - every column of `price_daily`, `fundamentals_quarterly` and `universe`
  (`features.get_catalog()`), with its formula, inputs and missing-value rules;
* screener view - the columns the package's screener view computes on top of them
  (PE, PFCF, ROE, ...), with the treatment the app relies on.

On top of the package's own fields the app adds two of its own: how the app uses the
column (`app_use`, from the same rule as the indicator dropdowns) and which columns are
built from it (`used_by`, the inputs read backwards). Nothing here reads data, only the
registry, so it is cheap and needs no build.
"""

from __future__ import annotations

import functools

import pandas as pd

import features
from features.registry import FREQUENCY, KEYS, UNITS
from features.views import screener

from . import indicators

LAYER_CANONICAL = "canonical"
LAYER_VIEW = "screener view"
VIEW_TABLE = "screener"  # id prefix of the view's own columns
RAW_PREFIX = "raw:"

USE_FUNDAMENTAL = "Indicator · fundamental"
USE_PRICE = "Indicator · price"
USE_ATTRIBUTE = "Ticker attribute"
USE_KEY = "Key"
USE_REPLACED = "Replaced by view rule"
USE_NOT_IN_VIEW = "Not in screener view"
HIDDEN_PREFIX = "Hidden · "

# The table's columns, in display order, with the header and the help text shown on
# hover and in the page's field glossary.
FIELDS = {
    "column": ("Column", "The column name, as read from the package."),
    "layer": ("Layer", "canonical: stored in the features build. screener view: computed on read "
                       "by features.views.screener, with the app's rules."),
    "table": ("Table", "Where the column lives: price_daily, fundamentals_quarterly, universe - "
                       "or screener for a column the view computes."),
    "frequency": ("Frequency", "One row per ticker and trading day (daily), per fiscal quarter "
                               "(quarterly), or per ticker (static)."),
    "category": ("Category", "The package's grouping; the indicator dropdowns are grouped by it."),
    "description": ("Description", "What the column is, in one sentence."),
    "unit": ("Unit", "How to read the number - see Units."),
    "app_use": ("In app", "Whether the app's pages offer this column, and if not, why."),
    "treatment": ("Treatment", "Screener view: the rule applied to the canonical value "
                               "(e.g. NaN for a negative denominator)."),
    "blanked_when": ("Blanked when", "Screener view: a condition under which the value is blanked."),
    "higher_is_better": ("Better", "Whether a higher or a lower value is the better one, where that is defined."),
    "is_valuation": ("Valuation", "A price-to-fundamental ratio: blank in the screener once the "
                                  "fundamentals are stale."),
    "formula": ("Formula", "How the package computes the column."),
    "inputs": ("Inputs", "Columns the formula reads. Bare name: same table. table.column: another "
                         "table (the quarter in force on each day). raw:file.column: an input file."),
    "denominators": ("Denominators", "Columns whose sign decides whether a ratio is a normal value."),
    "used_by_n": ("Used by", "How many columns are built from this one (listed in the details)."),
    "null_semantics": ("When missing", "When the value is missing, and why."),
    "values": ("Values", "Allowed labels of a text column."),
    "dtype": ("Dtype", "Storage type in the parquet files."),
    "version": ("Version", "Bumped by the package when the formula or the meaning changes."),
    "is_key": ("Key", "Part of the table's row key."),
    "is_forward_looking": ("Forward", "Uses data after the row's date - never offered in the app."),
}

PRESETS = {
    "user": ["column", "category", "description", "unit", "app_use", "treatment",
             "blanked_when", "higher_is_better"],
    "engineer": ["column", "layer", "table", "frequency", "category", "dtype", "unit", "formula",
                 "inputs", "denominators", "used_by_n", "null_semantics", "values", "version",
                 "is_forward_looking", "app_use"],
    "all": list(FIELDS),
}


def _yes(flag) -> str:
    return "yes" if flag else ""


def _better(flag) -> str:
    return {True: "higher", False: "lower"}.get(flag, "")


def _split(text) -> list[str]:
    return [p.strip() for p in str(text).split(",") if p.strip()] if isinstance(text, str) else []


def _ref_id(ref: str, table: str) -> str:
    """`table.column` id of an input reference; raw inputs keep their raw: form."""
    if ref.startswith(RAW_PREFIX):
        return ref
    head, dot, _ = ref.partition(".")
    return ref if dot and head in FREQUENCY else f"{table}.{ref}"


def _app_use(table: str, column: str, dtype: str, forward: bool, is_key: bool, in_view: set,
             computed: set) -> str:
    """How the app uses a canonical column - mirrors indicators.build_catalog(). A column
    the view computes under the same name (PS, ROA, ...) is shown in its view form."""
    if is_key:
        return USE_KEY
    if table == "universe":
        return USE_ATTRIBUTE
    if (table == "fundamentals_quarterly" and column in indicators.QUARTERLY_RULES) or (
        table == "price_daily" and column in computed
    ):
        return USE_REPLACED
    if table == "price_daily" and column not in in_view:
        return USE_NOT_IN_VIEW
    reason = indicators.not_offered_reason(column, dtype, forward)
    if reason:
        return HIDDEN_PREFIX + reason
    return USE_FUNDAMENTAL if table == "fundamentals_quarterly" else USE_PRICE


@functools.lru_cache(maxsize=1)
def get_docs() -> pd.DataFrame:
    """One row per documented column; `id` is `table.column` (`screener.PE` for the view)."""
    canonical = features.get_catalog()
    view = screener.catalog().set_index("column")
    passthrough = set(view.index[view["source"] == "canonical"])
    computed = set(view.index[view["source"] == "view"])

    rows = []
    for r in canonical.itertuples():
        in_view = r.table == "price_daily" and r.column in passthrough
        rows.append({
            "id": f"{r.table}.{r.column}",
            "column": r.column,
            "layer": LAYER_CANONICAL,
            "table": r.table,
            "frequency": r.frequency,
            "category": r.category,
            "description": r.description,
            "unit": r.unit,
            "app_use": _app_use(r.table, r.column, r.dtype, r.is_forward_looking, r.is_key, passthrough,
                                computed),
            "treatment": "",
            "blanked_when": (view.at[r.column, "blanked_when"] or "") if in_view else "",
            "higher_is_better": _better(r.higher_is_better),
            "is_valuation": _yes(r.is_valuation),
            "formula": r.formula,
            "input_ids": [_ref_id(i, r.table) for i in _split(r.inputs)],
            "inputs": r.inputs or "",
            "denominators": r.denominators if isinstance(r.denominators, str) else "",
            "null_semantics": r.null_semantics if isinstance(r.null_semantics, str) else "",
            "values": r.values if isinstance(r.values, str) else "",
            "dtype": r.dtype,
            "version": int(r.version),
            "is_key": _yes(r.is_key),
            "is_forward_looking": _yes(r.is_forward_looking),
        })

    for c in screener.COLUMNS:
        v = view.loc[c.name]
        dtype = "float32"  # every column the view computes is a float ratio
        reason = indicators.not_offered_reason(c.name, dtype, False)
        use = HIDDEN_PREFIX + reason if reason else (
            USE_FUNDAMENTAL if c.name in indicators.QUARTERLY_RULES else USE_PRICE
        )
        rows.append({
            "id": f"{VIEW_TABLE}.{c.name}",
            "column": c.name,
            "layer": LAYER_VIEW,
            "table": VIEW_TABLE,
            "frequency": "quarterly" if c.name in indicators.QUARTERLY_RULES else "daily",
            "category": c.category,
            "description": c.description,
            "unit": c.unit,
            "app_use": use,
            "treatment": c.treatment,
            "blanked_when": v["blanked_when"] or "",
            "higher_is_better": _better(c.higher_is_better),
            "is_valuation": _yes(c.is_valuation),
            "formula": "",
            "input_ids": [_ref_id(i, "price_daily") for i in c.inputs],
            "inputs": ", ".join(c.inputs),
            "denominators": "",
            "null_semantics": "",
            "values": "",
            "dtype": dtype,
            "version": None,
            "is_key": "",
            "is_forward_looking": "",
        })

    docs = pd.DataFrame(rows)
    used_by: dict[str, list[str]] = {}
    for fid, inputs in zip(docs["id"], docs["input_ids"]):
        for ref in inputs:
            used_by.setdefault(ref, []).append(fid)
    docs["used_by"] = [used_by.get(fid, []) for fid in docs["id"]]
    docs["used_by_n"] = docs["used_by"].str.len()
    # What the page's search box matches: every field the table can show.
    text = [docs[c].fillna("").astype(str) for c in FIELDS]
    docs["search_text"] = pd.concat(text, axis=1).agg(" ".join, axis=1).str.lower()
    return docs


def table_summary() -> pd.DataFrame:
    """One row per canonical table, plus the view: frequency, row key, column count."""
    docs = get_docs()
    rows = [
        {"table": t, "frequency": f, "key": ", ".join(KEYS[t]),
         "columns": int((docs["table"] == t).sum())}
        for t, f in FREQUENCY.items()
    ]
    rows.append({"table": VIEW_TABLE, "frequency": "daily (quarterly rules too)",
                 "key": "as price_daily", "columns": int((docs["table"] == VIEW_TABLE).sum())})
    return pd.DataFrame(rows)


def unit_summary() -> pd.DataFrame:
    """Every unit the package uses, its meaning and how many columns carry it."""
    counts = get_docs()["unit"].value_counts()
    return pd.DataFrame(
        {"unit": u, "meaning": meaning, "columns": int(counts.get(u, 0))}
        for u, meaning in UNITS.items()
    )
