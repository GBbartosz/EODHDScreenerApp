"""Configuration - build the portfolio that other pages select with one click.

The portfolio is a list of tickers in the root layout's local-storage store
(components.PORTFOLIO_STORE), so it survives closing the browser. Inspection,
Relative Performance and Indicator Distribution read it through the Portfolio
button in their filter panel.
"""

from __future__ import annotations

import dash
from dash import Input, Output, State, callback, dash_table, dcc, html

from .. import components, config, data

PAGE = "configuration"
LIST_COLUMNS = ("ticker", "name", config.SECTOR_COL, config.INDUSTRY_COL, "Status")


def _stock_options() -> list[dict]:
    """Every ticker, inactive ones too - a portfolio may hold a delisted stock."""
    return [
        {"label": f"{row.ticker} · {row.name} · {getattr(row, config.SECTOR_COL)}", "value": row.ticker}
        for row in data.get_stocks().itertuples()
    ]


def layout():
    return html.Div(
        [
            components.nav_bar("/configuration"),
            html.Main(
                [
                    html.H1("Configuration", className="page-title"),
                    html.P(
                        "Pick the stocks in your portfolio. They are saved in this "
                        "browser, and the Portfolio button on Inspection, Relative "
                        "Performance and Indicator Distribution selects them.",
                        className="page-subtitle",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Portfolio stocks", className="field-label"),
                                    dcc.Dropdown(
                                        id="cfg-portfolio",
                                        options=_stock_options(),
                                        value=[],
                                        multi=True,
                                        placeholder="Search by ticker or name",
                                    ),
                                ],
                                className="field field--wide",
                            ),
                        ],
                        className="filter-panel",
                    ),
                    html.Div(id="cfg-summary", className="summary"),
                    html.Div(id="cfg-list"),
                ],
                className="page",
            ),
        ]
    )


dash.register_page(__name__, path="/configuration", name="Configuration", order=8, layout=layout)


# Loading and saving are two callbacks, and the store is only a State in the
# first, so they do not trigger each other in a loop.


@callback(
    Output("cfg-portfolio", "value"),
    Input("cfg-portfolio", "id"),
    State(components.PORTFOLIO_STORE, "data"),
)
def _load(_id, portfolio):
    """Show the saved portfolio when the page opens, minus tickers no longer in the data."""
    known = set(data.get_stocks()["ticker"])
    return [t for t in (portfolio or []) if t in known]


@callback(
    Output(components.PORTFOLIO_STORE, "data"),
    Input("cfg-portfolio", "value"),
    prevent_initial_call=True,
)
def _save(tickers):
    return list(tickers or [])


@callback(
    Output("cfg-list", "children"),
    Output("cfg-summary", "children"),
    Input("cfg-portfolio", "value"),
)
def _update_list(tickers):
    if not tickers:
        return None, "The portfolio is empty."
    stocks = data.get_stocks().set_index("ticker")
    rows = []
    for t in tickers:
        if t not in stocks.index:
            continue
        stock = stocks.loc[t]
        rows.append(
            {
                "ticker": t,
                "name": stock["name"],
                config.SECTOR_COL: stock[config.SECTOR_COL],
                config.INDUSTRY_COL: stock[config.INDUSTRY_COL],
                "Status": "active" if stock["is_active"] else f"inactive since {stock['last_price_date']:%Y-%m-%d}",
            }
        )
    table = dash_table.DataTable(
        columns=[{"name": c.capitalize() if c.islower() else c, "id": c} for c in LIST_COLUMNS],
        data=rows,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={
            "fontFamily": "var(--font-mono)",
            "fontSize": "13px",
            "padding": "6px 10px",
            "textAlign": "left",
        },
        style_header={"fontWeight": "600", "backgroundColor": "var(--surface-2)"},
        style_data_conditional=[
            {"if": {"filter_query": '{Status} contains "inactive"'}, "color": "var(--muted)"}
        ],
    )
    return table, f"{len(rows)} stocks in the portfolio"
