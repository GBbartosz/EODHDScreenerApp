"""Screener - one row per ticker, showing the most recent data available.

Every value on this page comes from ``screener_latest.parquet``: the newest
price row for each ticker, with the fundamental quarter that was current at that
date joined on. That is why a row carries several dates - `date` is the trading
day, `fundamental date` is the quarter end behind the fundamental columns, and
`valuation date` is the day the price-to-fundamentals ratios (P/E, EV/EBITDA, ...)
are taken from. Once a newer quarter is due than the data holds, those ratios
stop being trustworthy, so they are shown as of the last day they still were.
"""

from __future__ import annotations

import dash
from dash import Input, Output, callback, dash_table, dcc, html

from .. import components, config, data, indicators

PAGE = "screener"


def layout():
    return html.Div(
        [
            components.nav_bar("/screener"),
            html.Main(
                [
                    html.H1("Screener", className="page-title"),
                    components.filter_panel(PAGE),
                    html.Div(
                        [
                            html.Label("Indicators", className="field-label"),
                            dcc.Dropdown(
                                id="screener-indicators",
                                options=data.get_indicator_options(),
                                value=list(config.DEFAULT_SCREENER_INDICATORS),
                                multi=True,
                                placeholder="Pick indicators to show",
                            ),
                        ],
                        className="field",
                    ),
                    html.Div(id="screener-summary", className="summary"),
                    dcc.Loading(
                        html.Div(id="screener-table-wrap"),
                        type="default",
                    ),
                ],
                className="page",
            ),
        ]
    )


# See the note in home.py: registration happens after `layout` exists so it can
# be passed explicitly.
dash.register_page(__name__, path="/screener", name="Screener", order=1, layout=layout)


def _columns(selected: list[str]):
    """Leading key columns first, then the chosen indicators in the chosen order."""
    catalog = data.get_catalog()
    columns = [
        {
            "name": config.LEADING_COLUMN_LABELS[c],
            "id": c,
            "type": "datetime" if c != "ticker" else "text",
        }
        for c in config.LEADING_COLUMNS
    ]

    for column in selected:
        indicator = catalog.get(column)
        if indicator is None:
            continue
        columns.append(
            {
                "name": column,
                "id": column,
                "type": "numeric",
                "format": indicators.table_format(indicator),
            }
        )
    return columns


@callback(
    Output("screener-table-wrap", "children"),
    Output("screener-summary", "children"),
    Input(components.fid("sector", PAGE), "value"),
    Input(components.fid("industry", PAGE), "value"),
    Input(components.fid("stock", PAGE), "value"),
    Input(components.fid("active", PAGE), "value"),
    Input("screener-indicators", "value"),
)
def _update_table(sectors, industries, tickers, active, selected):
    universe = data.filter_universe(
        sectors, industries, tickers, active_only=components.wants_active_only(active)
    )
    frame = data.get_screener()
    frame = frame[frame["ticker"].isin(universe["ticker"])]

    selected = [c for c in (selected or []) if c in data.get_catalog()]
    columns = _columns(selected)
    visible = [c["id"] for c in columns]

    # Dates render as plain YYYY-MM-DD and still sort chronologically.
    display = frame.loc[:, [c for c in visible if c in frame.columns]].copy()
    for column in config.LEADING_COLUMNS:
        if column != "ticker" and column in display.columns:
            display[column] = display[column].dt.strftime("%Y-%m-%d")

    table = dash_table.DataTable(
        id="screener-table",
        columns=columns,
        data=display.to_dict("records"),
        sort_action="native",
        sort_mode="multi",
        filter_action="native",
        page_size=25,
        fixed_rows={"headers": True},
        style_table={"overflowX": "auto", "maxHeight": "68vh"},
        style_cell={
            "fontFamily": "var(--font-mono)",
            "fontSize": "13px",
            "padding": "6px 10px",
            "textAlign": "right",
            "minWidth": "90px",
        },
        style_cell_conditional=[
            {"if": {"column_id": c}, "textAlign": "left"} for c in config.LEADING_COLUMNS
        ],
        style_header={
            "fontWeight": "600",
            "backgroundColor": "var(--surface-2)",
            "textAlign": "right",
        },
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "var(--surface-2)"}
        ],
    )

    summary = f"{len(display):,} tickers · {len(selected)} indicators"
    return table, summary
