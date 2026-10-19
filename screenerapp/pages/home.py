"""Landing page - a directory of everything else in the app."""

from __future__ import annotations

import dash
from dash import dcc, html

import features

from .. import components, data

BLURBS = {
    "/screener": "Rank the current universe on any combination of indicators.",
    "/relative-performance": "Compare price moves from a common starting point, in percent.",
    "/heatmap": "Price change by sector, sized by market capitalisation.",
    "/indicator-distribution": "See where a stock falls within the market's spread of an indicator.",
    "/inspection": "Track two indicators through time for the stocks you pick.",
    "/dcf": "Value a stock on its cash flow, and reverse-engineer what the price assumes.",
    "/features": "What every feature means, how it is computed and where the app uses it.",
}


def _card(page) -> dcc.Link:
    return dcc.Link(
        [
            html.H3(page["name"], className="card-title"),
            html.P(BLURBS.get(page["path"], ""), className="card-text"),
        ],
        href=page["path"],
        className="card",
    )


def layout():
    pages = [
        p
        for p in sorted(dash.page_registry.values(), key=lambda p: p.get("order", 99))
        if p["path"] != "/"
    ]

    try:
        meta = data.get_meta()
        summary = (
            f"{meta['n_active']:,} active of {meta['n_tickers']:,} tickers · "
            f"prices through {meta['price_date_max']} · "
            f"fundamentals downloaded {meta['fund_snapshot']}"
        )
    except features.FeaturesError as exc:
        summary = str(exc)

    return html.Div(
        [
            components.nav_bar("/"),
            html.Main(
                [
                    html.H1("Stock Screener", className="page-title"),
                    html.P(summary, className="page-subtitle"),
                    html.Div([_card(p) for p in pages], className="card-grid"),
                ],
                className="page",
            ),
        ]
    )


# Registered at the bottom, with `layout` passed explicitly: app.py turns off
# Dash's folder discovery (so these modules stay importable as a package), and
# that discovery is what would otherwise attach `module.layout` after import.
dash.register_page(__name__, path="/", name="Home", order=0, layout=layout)
