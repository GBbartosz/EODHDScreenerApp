"""Shared UI: the navigation bar and the sector/industry/stock filter panel.

The filter panel appears on every analysis page, so its components use
pattern-matching ids keyed by page (``{"component": "sector", "page": "screener"}``).
One set of MATCH callbacks below drives the cascade on all of them - a new page
gets working filters just by calling ``filter_panel("its-name")``.
"""

from __future__ import annotations

import dash
from dash import MATCH, Input, Output, State, callback, ctx, dcc, html

from . import config, data

INACTIVE_OPTION = "include_inactive"

# Pages whose stock dropdown keeps offering the whole universe no matter what
# sector or industry is selected. On the distribution page those dropdowns choose
# the group a stock is being *compared against*, so narrowing the stock list to
# them would make the only interesting comparison - a stock against a sector it
# does not belong to - impossible to set up.
FULL_UNIVERSE_STOCK_PAGES = frozenset({"indicator-distribution"})


def fid(component: str, page: str) -> dict:
    """Pattern-matching id for a filter component on a given page."""
    return {"component": component, "page": page}


def nav_bar(active_path: str) -> html.Nav:
    """Links to every registered page, ordered by each page's `order`."""
    pages = sorted(dash.page_registry.values(), key=lambda p: p.get("order", 99))
    links = [
        dcc.Link(
            page["name"],
            href=page["path"],
            className="nav-link" + (" nav-link--active" if page["path"] == active_path else ""),
        )
        for page in pages
    ]
    return html.Nav(
        [html.Span("ScreenerApp", className="nav-brand"), html.Div(links, className="nav-links")],
        className="nav-bar",
    )


def filter_panel(page: str, *, include_active_toggle: bool = True) -> html.Div:
    """Sector / industry / stock multi-selects, plus the inactive-ticker toggle.

    Nothing is selected by default, which means "no restriction".
    """
    children = [
        html.Div(
            [
                html.Label("Sector", className="field-label"),
                dcc.Dropdown(
                    id=fid("sector", page),
                    options=data.get_sector_options(),
                    value=[],
                    multi=True,
                    placeholder="All sectors",
                ),
            ],
            className="field",
        ),
        html.Div(
            [
                html.Label("Industry", className="field-label"),
                dcc.Dropdown(
                    id=fid("industry", page),
                    options=[],
                    value=[],
                    multi=True,
                    placeholder="All industries",
                ),
            ],
            className="field",
        ),
        html.Div(
            [
                html.Label("Stock", className="field-label"),
                dcc.Dropdown(
                    id=fid("stock", page),
                    options=[],
                    value=[],
                    multi=True,
                    placeholder="All stocks",
                ),
            ],
            className="field field--wide",
        ),
    ]

    if include_active_toggle:
        children.append(
            html.Div(
                [
                    html.Label("Universe", className="field-label"),
                    dcc.Checklist(
                        id=fid("active", page),
                        options=[{"label": "Include inactive", "value": INACTIVE_OPTION}],
                        value=[],
                        className="checklist",
                    ),
                ],
                className="field field--narrow",
            )
        )
    else:
        # Keep the id present so the MATCH callbacks still resolve.
        children.append(
            dcc.Checklist(id=fid("active", page), options=[], value=[], style={"display": "none"})
        )

    return html.Div(children, className="filter-panel")


def wants_active_only(active_value: list[str] | None) -> bool:
    """The checkbox is opt-in, so an empty value means "active tickers only"."""
    return INACTIVE_OPTION not in (active_value or [])


# --- cascade ---------------------------------------------------------------


@callback(
    Output(fid("industry", MATCH), "options"),
    Output(fid("industry", MATCH), "value"),
    Input(fid("sector", MATCH), "value"),
    Input(fid("active", MATCH), "value"),
    State(fid("industry", MATCH), "value"),
)
def _update_industries(sectors, active, current):
    """Limit industries to the chosen sectors, dropping selections that no longer fit."""
    universe = data.filter_universe(sectors, None, active_only=wants_active_only(active))
    available = sorted(universe[config.INDUSTRY_COL].dropna().unique())
    options = [{"label": v, "value": v} for v in available]
    kept = [v for v in (current or []) if v in available]
    return options, kept


@callback(
    Output(fid("stock", MATCH), "options"),
    Output(fid("stock", MATCH), "value"),
    Input(fid("sector", MATCH), "value"),
    Input(fid("industry", MATCH), "value"),
    Input(fid("active", MATCH), "value"),
    State(fid("stock", MATCH), "value"),
)
def _update_stocks(sectors, industries, active, current):
    """Limit tickers to the chosen sectors/industries, unless the page opts out."""
    page = ctx.outputs_list[0]["id"]["page"]
    if page in FULL_UNIVERSE_STOCK_PAGES:
        sectors, industries = None, None

    universe = data.filter_universe(
        sectors, industries, active_only=wants_active_only(active)
    )
    available = list(universe["ticker"])
    options = [
        {"label": f"{row.ticker} · {getattr(row, config.SECTOR_COL)}", "value": row.ticker}
        for row in universe.itertuples()
    ]
    kept = [v for v in (current or []) if v in available]
    return options, kept
