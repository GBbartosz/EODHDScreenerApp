"""Feature documentation - every column of the features package, searchable.

For the app's user: what an indicator means, its unit, which way is better and why it
may be blank. For the engineer: the table it lives in, its formula, inputs, dependents,
missing-value rule and version. The data is the package's registry (see
feature_docs.py), so the page needs no features build and is always in step with it.
"""

from __future__ import annotations

import dash
import pandas as pd
from dash import ALL, Input, Output, callback, ctx, dash_table, dcc, html

import features

from .. import components, data, feature_docs as fd

SECTIONS = (
    ("overview", "Overview"),
    ("catalog", "Feature table"),
    ("tables", "Tables"),
    ("units", "Units"),
    ("in-app", "In app"),
    ("fields", "Fields"),
)
APP_USE_HELP = (
    (fd.USE_FUNDAMENTAL, "Offered in the indicator dropdowns, read from quarterly rows."),
    (fd.USE_PRICE, "Offered in the indicator dropdowns, read from daily rows through the screener view."),
    (fd.USE_ATTRIBUTE, "Describes the ticker (name, sector, currency, ...): used for filters and labels."),
    (fd.USE_KEY, "Row key of its table (ticker, date)."),
    (fd.USE_REPLACED, "The screener view computes a column of the same name with the app's rule "
                      "(e.g. NaN for a negative denominator); the app shows that one."),
    (fd.USE_NOT_IN_VIEW, "A daily column the screener view does not pass through."),
    (fd.HIDDEN_PREFIX + "...", "Kept out of the dropdowns: not a number, uses the future, or a "
                               "duplicate shown under another name (*_signed, *_local)."),
)
WIDE_FIELDS = {"description": 320, "formula": 320, "null_semantics": 300, "treatment": 260,
               "inputs": 240, "denominators": 220, "blanked_when": 160}


def _filter_value(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


# --- layout pieces ---------------------------------------------------------


def _quick_filters(title: str, field: str, counts) -> html.Div:
    buttons = [
        html.Button(
            [html.Span(value, className="docs-chip-label"), html.Span(f"{n}", className="docs-chip-count")],
            id={"type": "fdoc-quick", "field": field, "value": value},
            className="docs-chip",
            title=f"Show only {field} = {value}",
        )
        for value, n in counts.items()
    ]
    return html.Div([html.Div(title, className="docs-nav-title"), *buttons], className="docs-nav-group")


def _side_nav(docs) -> html.Aside:
    return html.Aside(
        [
            html.Div(
                [html.Div("On this page", className="docs-nav-title")]
                + [html.A(label, href=f"#{anchor}", className="docs-nav-link") for anchor, label in SECTIONS],
                className="docs-nav-group",
            ),
            html.Button("Clear table filters", id="fdoc-clear", className="docs-clear"),
            _quick_filters("Layer", "layer", docs["layer"].value_counts(sort=False)),
            _quick_filters("Table", "table", docs["table"].value_counts(sort=False)),
            _quick_filters("Category", "category", docs["category"].value_counts().sort_index()),
        ],
        className="docs-nav",
    )


def _stat(label: str, value, note: str = "") -> html.Div:
    return html.Div(
        [html.Div(label, className="stat-label"), html.Div(value, className="stat-value"),
         html.Div(note, className="stat-note")],
        className="stat",
    )


def _overview(docs) -> html.Section:
    offered = docs["app_use"].str.startswith("Indicator").sum()
    try:
        manifest = data.get_meta()
        build = f"built {manifest['built_at']}"
    except features.FeaturesError:
        build = "no features build found"
    return html.Section(
        [
            html.H1("Features", className="page-title"),
            html.P(
                "Every column the features package defines: what it means, how it is computed "
                "and how this app uses it. Use the menu on the left to jump to a section or "
                "narrow the table; click a row of the table for the full record. Tables, units "
                "and a glossary of the fields are below the table.",
                className="page-subtitle",
            ),
            html.Div(
                [
                    _stat("Columns documented", f"{len(docs):,}", "canonical and screener view"),
                    _stat("Canonical", f"{(docs['layer'] == fd.LAYER_CANONICAL).sum():,}",
                          "stored in the features build"),
                    _stat("Screener view", f"{(docs['layer'] == fd.LAYER_VIEW).sum():,}",
                          "computed on read, with the app's rules"),
                    _stat("Offered in the app", f"{offered:,}", "in the indicator dropdowns"),
                    _stat("Package", f"features {features.__version__}", build),
                ],
                className="stat-grid",
            ),
        ],
        id="overview",
    )


def _ref_table(frame, columns: dict[str, str]) -> html.Table:
    head = html.Thead(html.Tr([html.Th(label) for label in columns.values()]))
    body = html.Tbody(
        [html.Tr([html.Td(row[c]) for c in columns]) for row in frame.to_dict("records")]
    )
    return html.Table([head, body], className="docs-ref-table")


def _reference_sections() -> list[html.Section]:
    return [
        html.Section(
            [
                html.H2("Tables", className="section-title"),
                html.P("The package stores three tables; the screener view adds its own columns "
                       "on top of price_daily when the app reads it.", className="docs-text"),
                _ref_table(fd.table_summary(),
                           {"table": "Table", "frequency": "Frequency", "key": "Row key", "columns": "Columns"}),
            ],
            id="tables",
        ),
        html.Section(
            [
                html.H2("Units", className="section-title"),
                _ref_table(fd.unit_summary(), {"unit": "Unit", "meaning": "Meaning", "columns": "Columns"}),
            ],
            id="units",
        ),
        html.Section(
            [
                html.H2("How the app uses a column", className="section-title"),
                html.P("The In app field of the feature table. The app's rules on top of the "
                       "package (stale fundamentals, USD conversion, active tickers) are in README.md.",
                       className="docs-text"),
                _ref_table(
                    pd.DataFrame(APP_USE_HELP, columns=["use", "meaning"]),
                    {"use": "In app", "meaning": "Meaning"},
                ),
            ],
            id="in-app",
        ),
        html.Section(
            [
                html.H2("Fields", className="section-title"),
                html.P("What each field of the feature table holds. Hover a header in the table for "
                       "the same text.", className="docs-text"),
                html.Dl(
                    [item for label, help_text in fd.FIELDS.values()
                     for item in (html.Dt(label), html.Dd(help_text))],
                    className="docs-fields",
                ),
            ],
            id="fields",
        ),
    ]


def _catalog_section(docs) -> html.Section:
    columns = [
        {"id": c, "name": label, "hideable": c != "column",
         **({"type": "numeric"} if c in ("version", "used_by_n") else {})}
        for c, (label, _) in fd.FIELDS.items()
    ]
    table = dash_table.DataTable(
        id="fdoc-table",
        columns=columns,
        data=_records(docs),
        hidden_columns=_hidden("user"),
        sort_action="native",
        sort_mode="multi",
        filter_action="native",
        filter_options={"case": "insensitive"},
        page_action="native",
        page_size=20,
        tooltip_header={c: help_text for c, (_, help_text) in fd.FIELDS.items()},
        tooltip_delay=300,
        tooltip_duration=None,
        css=[{"selector": ".show-hide", "rule": "font-family: var(--font-sans); margin: 4px 0 8px;"}],
        style_table={"overflowX": "auto"},
        style_cell={
            "fontFamily": "var(--font-sans)",
            "fontSize": "13px",
            "padding": "6px 10px",
            "textAlign": "left",
            "minWidth": "80px",
            "maxWidth": "200px",
            "whiteSpace": "normal",
            "height": "auto",
            "verticalAlign": "top",
            "cursor": "pointer",
        },
        style_cell_conditional=[
            {"if": {"column_id": "column"}, "fontFamily": "var(--font-mono)", "fontWeight": "600",
             "minWidth": "180px"},
            *({"if": {"column_id": c}, "minWidth": f"{w}px", "maxWidth": f"{w}px"} for c, w in WIDE_FIELDS.items()),
            *({"if": {"column_id": c}, "fontFamily": "var(--font-mono)", "fontSize": "12px"}
              for c in ("formula", "inputs", "denominators", "dtype", "unit")),
        ],
        style_header={"fontWeight": "600", "backgroundColor": "var(--surface-2)", "whiteSpace": "normal"},
        style_filter={"backgroundColor": "var(--surface-1)"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "var(--surface-2)"},
            {"if": {"filter_query": '{app_use} contains "Hidden"', "column_id": "app_use"},
             "color": "var(--muted)"},
            {"if": {"filter_query": '{app_use} contains "Indicator"', "column_id": "app_use"},
             "color": "var(--accent)"},
            {"if": {"state": "active"}, "backgroundColor": "rgba(42, 120, 214, 0.08)",
             "border": "1px solid var(--accent)"},
        ],
    )
    controls = html.Div(
        [
            html.Div(
                [
                    html.Label("Search", className="field-label", htmlFor="fdoc-search"),
                    dcc.Input(id="fdoc-search", type="search", debounce=0.3, className="number-input docs-search",
                              placeholder="Any field: name, description, formula, input ..."),
                ],
                className="field field--wide",
            ),
            html.Div(
                [
                    html.Label("Columns shown", className="field-label"),
                    dcc.RadioItems(
                        id="fdoc-preset",
                        options=[{"label": "User", "value": "user"},
                                 {"label": "Engineer", "value": "engineer"},
                                 {"label": "All fields", "value": "all"}],
                        value="user",
                        inline=True,
                        className="checklist docs-radio",
                    ),
                ],
                className="field",
            ),
            html.Div(
                [
                    html.Label("In app", className="field-label"),
                    dcc.Checklist(id="fdoc-offered",
                                  options=[{"label": "Offered in the app only", "value": "offered"}],
                                  value=[], className="checklist"),
                ],
                className="field field--narrow",
            ),
        ],
        className="filter-panel",
    )
    return html.Section(
        [
            html.H2("Feature table", className="section-title"),
            html.P(
                "Sort by clicking a header (shift-click for several), filter with the row under "
                "the headers (e.g. > 0, contains TTM, = Margins), and use Toggle Columns to add "
                "or remove fields.",
                className="docs-text",
            ),
            controls,
            html.Div(id="fdoc-summary", className="summary"),
            html.Div(
                [html.Div(table, className="docs-table"),
                 html.Div(id="fdoc-details", className="docs-details")],
                className="docs-catalog",
            ),
        ],
        id="catalog",
    )


def _records(docs) -> list[dict]:
    shown = ["id", *fd.FIELDS]
    return docs[shown].to_dict("records")


def _hidden(preset: str) -> list[str]:
    keep = set(fd.PRESETS[preset])
    return [c for c in fd.FIELDS if c not in keep]


def layout():
    docs = fd.get_docs()
    return html.Div(
        [
            components.nav_bar("/features"),
            html.Main(
                html.Div(
                    [
                        _side_nav(docs),
                        html.Div(
                            [_overview(docs), _catalog_section(docs), *_reference_sections()],
                            className="docs-content",
                        ),
                    ],
                    className="docs-layout",
                ),
                className="page page--wide",
            ),
            dcc.Store(id="fdoc-selected"),
        ]
    )


# --- callbacks -------------------------------------------------------------


@callback(
    Output("fdoc-table", "data"),
    Output("fdoc-summary", "children"),
    Input("fdoc-search", "value"),
    Input("fdoc-offered", "value"),
)
def _search(text, offered):
    """Global search across every field, then the "offered only" switch. The header
    filters and sorting run in the browser on top of what this returns."""
    docs = fd.get_docs()
    if offered:
        docs = docs[docs["app_use"].str.startswith("Indicator")]
    if text and text.strip():
        for word in text.lower().split():
            docs = docs[docs["search_text"].str.contains(word, regex=False)]
    total = len(fd.get_docs())
    summary = f"{len(docs):,} of {total:,} columns" + (" (header filters may narrow it further)" if len(docs) else "")
    return _records(docs), summary


@callback(Output("fdoc-table", "hidden_columns"), Input("fdoc-preset", "value"))
def _preset(preset):
    return _hidden(preset or "user")


@callback(
    Output("fdoc-table", "filter_query"),
    Output("fdoc-table", "page_current"),
    Input({"type": "fdoc-quick", "field": ALL, "value": ALL}, "n_clicks"),
    Input("fdoc-clear", "n_clicks"),
    prevent_initial_call=True,
)
def _quick_filter(_quick, _clear):
    """Side-menu chips set a header filter, so it shows (and can be edited) in the table."""
    trigger = ctx.triggered_id
    if not ctx.triggered or not ctx.triggered[0]["value"] or trigger == "fdoc-clear":
        return "", 0
    return f"{{{trigger['field']}}} = {_filter_value(trigger['value'])}", 0


@callback(
    Output("fdoc-selected", "data"),
    Input("fdoc-table", "active_cell"),
    Input({"type": "fdoc-link", "id": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _select(active_cell, _links):
    """A table row, or an input / dependent link in the details panel."""
    trigger = ctx.triggered_id
    if isinstance(trigger, dict):
        if not ctx.triggered[0]["value"]:  # the links were just rendered, not clicked
            return dash.no_update
        return trigger["id"]
    return (active_cell or {}).get("row_id") or dash.no_update


def _link(feature_id: str, known: set) -> html.Component:
    if feature_id in known:
        return html.Button(feature_id, id={"type": "fdoc-link", "id": feature_id}, className="docs-link")
    return html.Span(feature_id, className="docs-raw")


def _detail_row(label: str, value) -> list:
    if value in ("", None) or (isinstance(value, list) and not value):
        return []
    return [html.Dt(label), html.Dd(value)]


@callback(Output("fdoc-details", "children"), Input("fdoc-selected", "data"))
def _details(feature_id):
    docs = fd.get_docs()
    match = docs[docs["id"] == feature_id]
    if match.empty:
        return html.Div(
            [html.Div("Details", className="docs-nav-title"),
             html.P("Click a row of the table to see its full record, with links to the "
                    "columns it is built from and the columns built from it.", className="docs-text")],
            className="docs-details-empty",
        )
    row = match.iloc[0]
    known = set(docs["id"])
    flags = [label for flag, label in (("is_key", "key"), ("is_valuation", "valuation"),
                                       ("is_forward_looking", "forward-looking")) if row[flag]]
    if row["higher_is_better"]:
        flags.append(f"{row['higher_is_better']} is better")
    items = [
        *_detail_row("In app", row["app_use"]),
        *_detail_row("Layer", row["layer"]),
        *_detail_row("Table", f"{row['table']} · {row['frequency']}"),
        *_detail_row("Category", row["category"]),
        *_detail_row("Unit", f"{row['unit']} - {fd.UNITS.get(row['unit'], '')}"),
        *_detail_row("Dtype", row["dtype"]),
        *_detail_row("Flags", ", ".join(flags)),
        *_detail_row("Formula", html.Code(row["formula"]) if row["formula"] else ""),
        *_detail_row("Treatment", row["treatment"]),
        *_detail_row("Blanked when", row["blanked_when"]),
        *_detail_row("When missing", row["null_semantics"]),
        *_detail_row("Values", row["values"]),
        *_detail_row("Denominators", row["denominators"]),
        *_detail_row("Inputs", [_link(i, known) for i in row["input_ids"]]),
        *_detail_row(f"Used by ({len(row['used_by'])})", [_link(i, known) for i in row["used_by"]]),
        *_detail_row("Version", "" if pd.isna(row["version"]) else str(int(row["version"]))),
    ]
    return [
        html.Div("Details", className="docs-nav-title"),
        html.H3(row["column"], className="docs-details-title"),
        html.Div(row["id"], className="docs-details-id"),
        html.P(row["description"], className="docs-text"),
        html.Dl(items, className="docs-fields docs-fields--compact"),
    ]


# Registered at the bottom with `layout` passed explicitly - see home.py.
dash.register_page(__name__, path="/features", name="Features", order=7, layout=layout)
