"""Market heatmap - price change laid out by sector, sized by market cap.

Structurally this is a treemap rather than a grid heatmap, which is what the
brief describes: tiles nested sector > industry > ticker, area proportional to
market capitalisation, fill carrying the price change.

The colour scale is deliberately fixed rather than fitted to the day on screen.
A day where everything fell should look red, not get rescaled until the least
bad stock turns green - so the bound is a control, not a function of the data.
"""

from __future__ import annotations

import dash
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html

from .. import components, config, data, theme

PAGE = "heatmap"

# Covers 94% of single-day moves; widen it for longer windows.
DEFAULT_BOUND_PCT = 5.0

# What each mode measures, and how it should be coloured.
#
# Price change is two-sided, so it keeps the diverging scale with its midpoint
# pinned at zero. The other two cannot cross zero - the last price is never
# above the window's high nor below its low - so they take a single arm of the
# same palette and use its whole range.
MODES = {
    "price": {
        "label": "Start-End",
        "colourbar": "Change %",
        "bound": 5.0,
        "one_sided": None,
    },
    "ath": {
        "label": "ATH",
        "colourbar": "From high %",
        "bound": 30.0,
        "one_sided": "down",
    },
    "bottom": {
        "label": "Bottom",
        "colourbar": "From low %",
        "bound": 50.0,
        "one_sided": "up",
    },
}


def _cap_weighted(group: pd.DataFrame) -> float:
    """Change of a sector or industry as one position, not an average of names.

    A simple mean would let a handful of micro caps outvote the index heavyweight
    sitting next to them.
    """
    return float(np.average(group["change_pct"], weights=group["MarketCap"]))


def _build_nodes(frame: pd.DataFrame, depth: str) -> pd.DataFrame:
    """Flatten the sector > industry > ticker hierarchy into treemap nodes.

    Built by hand rather than with plotly express because the tile label has to
    show the numeric change: in a treemap `%{color}` resolves to the rendered
    fill colour, so the value has to travel in customdata - and express only
    fills customdata for leaves, which would leave every parent tile blank.
    """
    rows = [
        {
            "id": "Market",
            "label": "Market",
            "parent": "",
            "value": float(frame["MarketCap"].sum()),
            "change": _cap_weighted(frame),
        }
    ]

    for sector, sector_rows in frame.groupby(config.SECTOR_COL, sort=False):
        sector_id = f"S|{sector}"
        rows.append(
            {
                "id": sector_id,
                "label": sector,
                "parent": "Market",
                "value": float(sector_rows["MarketCap"].sum()),
                "change": _cap_weighted(sector_rows),
            }
        )

        if depth == "industry":
            for industry, industry_rows in sector_rows.groupby(
                config.INDUSTRY_COL, sort=False
            ):
                industry_id = f"I|{sector}|{industry}"
                rows.append(
                    {
                        "id": industry_id,
                        "label": industry,
                        "parent": sector_id,
                        "value": float(industry_rows["MarketCap"].sum()),
                        "change": _cap_weighted(industry_rows),
                    }
                )
                rows.extend(_leaf_rows(industry_rows, industry_id))
        else:
            rows.extend(_leaf_rows(sector_rows, sector_id))

    nodes = pd.DataFrame(rows)
    nodes["prices"] = nodes["prices"].fillna("")
    return nodes


def _leaf_rows(rows: pd.DataFrame, parent: str) -> list[dict]:
    return [
        {
            "id": f"T|{row.ticker}",
            "label": row.ticker,
            "parent": parent,
            "value": float(row.MarketCap),
            "change": float(row.change_pct),
            "prices": _price_lines(row),
        }
        for row in rows.itertuples()
    ]


def _price_lines(row) -> str:
    """Hover lines for one ticker: the window's high, end and low closes.

    Parent tiles have no single price, so the lines travel as one pre-built
    string that is simply empty for them.
    """
    currency = row.currency if isinstance(row.currency, str) else ""

    def price(value, date) -> str:
        return f"{value:,.2f} {currency}  ({pd.Timestamp(date).date()})"

    return (
        f"<br>ATH  {price(row.high, row.high_date)}"
        f"<br>End  {price(row.end_price, row.end_date)}"
        f"<br>Bottom  {price(row.low, row.low_date)}"
    )


def _default_dates() -> tuple[pd.Timestamp, pd.Timestamp]:
    """The two most recent sessions - a one-day change."""
    dates = data.get_trading_dates()
    if len(dates) < 2:
        return dates[-1], dates[-1]
    return dates[-2], dates[-1]


def layout():
    start, end = _default_dates()
    dates = data.get_trading_dates()

    return html.Div(
        [
            components.nav_bar("/heatmap"),
            html.Main(
                [
                    html.H1("Heatmap", className="page-title"),
                    html.P(
                        "Price change by sector and industry. Tile area is market "
                        "capitalisation; colour is the change over the chosen window.",
                        className="page-subtitle",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Change from", className="field-label"),
                                    dcc.RadioItems(
                                        id="hm-mode",
                                        options=[
                                            {"label": cfg["label"], "value": key}
                                            for key, cfg in MODES.items()
                                        ],
                                        value="price",
                                        className="checklist",
                                    ),
                                ],
                                className="field field--narrow",
                            ),
                            html.Div(
                                [
                                    html.Label("Window", className="field-label"),
                                    dcc.DatePickerRange(
                                        id="hm-dates",
                                        min_date_allowed=dates[0],
                                        max_date_allowed=dates[-1],
                                        start_date=start,
                                        end_date=end,
                                        display_format="YYYY-MM-DD",
                                    ),
                                ],
                                className="field field--narrow",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Colour scale ± %", className="field-label"
                                    ),
                                    dcc.Input(
                                        id="hm-bound",
                                        type="number",
                                        value=DEFAULT_BOUND_PCT,
                                        # The browser counts steps from `min`: with
                                        # min 0.1 a value of 5 is off-grid, so the
                                        # input reports it invalid and blanks it.
                                        min=0.5,
                                        step=0.5,
                                        # Seconds, so +/- clicks redraw once they stop
                                        # rather than only on Enter or blur.
                                        debounce=0.5,
                                        className="number-input",
                                    ),
                                ],
                                className="field field--narrow",
                            ),
                            html.Div(
                                [
                                    html.Label("Depth", className="field-label"),
                                    dcc.RadioItems(
                                        id="hm-depth",
                                        options=[
                                            {"label": "Sector", "value": "sector"},
                                            {"label": "Industry", "value": "industry"},
                                        ],
                                        value="industry",
                                        className="checklist",
                                    ),
                                ],
                                className="field field--narrow",
                            ),
                        ],
                        className="filter-panel",
                    ),
                    html.Div(id="hm-summary", className="summary"),
                    dcc.Loading(
                        dcc.Graph(
                            id="hm-chart",
                            style={"height": "72vh"},
                            config={"displaylogo": False},
                        ),
                        type="default",
                    ),
                ],
                className="page",
            ),
        ]
    )


dash.register_page(__name__, path="/heatmap", name="Heatmap", order=3, layout=layout)


@callback(
    Output("hm-bound", "value"),
    Input("hm-mode", "value"),
)
def _bound_for_mode(mode):
    """Reset the scale to something sensible for the measure being switched to.

    A 5% span reads a single day well but leaves every drawdown pinned to the
    dark end. The bound stays a fixed number you can overwrite - it is never
    fitted to the data on screen.
    """
    return MODES.get(mode or "price", MODES["price"])["bound"]


def _frame_for_mode(start, end, mode):
    """One row per ticker with `change_pct` meaning whatever the mode measures.

    Every mode also carries the window's high, low and end close (with dates)
    for the hover, so the percentage can be checked against the prices behind it.
    """
    extremes = data.get_price_extremes(start, end)
    if extremes.empty:
        return extremes

    if mode == "price":
        # Start-End keeps its own rule - priced on both end dates - and only
        # borrows the high and low from the window.
        frame = data.get_price_change(start, end).rename(columns={"close_end": "end_price"})
        frame["end_date"] = end
        frame = frame.merge(
            extremes[["ticker", "high", "high_date", "low", "low_date"]], on="ticker"
        )
    else:
        reference = "high" if mode == "ath" else "low"
        frame = extremes[extremes[reference] > 0].rename(
            columns={"last": "end_price", "last_date": "end_date"}
        )
        frame["change_pct"] = (frame["end_price"] / frame[reference] - 1) * 100

    currency = data.get_stocks()[["ticker", "currency"]]
    return frame.merge(currency, on="ticker", how="left")


@callback(
    Output("hm-chart", "figure"),
    Output("hm-summary", "children"),
    Input("hm-dates", "start_date"),
    Input("hm-dates", "end_date"),
    Input("hm-bound", "value"),
    Input("hm-depth", "value"),
    Input("hm-mode", "value"),
)
def _update_heatmap(start_date, end_date, bound, depth, mode):
    start = data.snap_to_trading_date(start_date)
    end = data.snap_to_trading_date(end_date)
    mode = mode or "price"
    config_for_mode = MODES.get(mode, MODES["price"])

    if start >= end:
        return (
            theme.empty_figure("Pick an end date after the start date."),
            "",
        )

    frame = _frame_for_mode(start, end, mode)
    if frame.empty:
        return theme.empty_figure("No price data for this window."), ""

    bound = abs(float(bound)) if bound else config_for_mode["bound"]

    one_sided = config_for_mode["one_sided"]
    if one_sided == "down":
        scale, colour_min, colour_max = theme.SEQUENTIAL_LOSS, -bound, 0.0
    elif one_sided == "up":
        scale, colour_min, colour_max = theme.SEQUENTIAL_GAIN, 0.0, bound
    else:
        scale, colour_min, colour_max = theme.DIVERGING_LOSS_GAIN, -bound, bound

    nodes = _build_nodes(frame, depth)

    figure = go.Figure(
        go.Treemap(
            ids=nodes["id"],
            labels=nodes["label"],
            parents=nodes["parent"],
            values=nodes["value"],
            text=[f"{value:+.1f}%" for value in nodes["change"]],
            # Pre-formatted strings rather than numbers: a treemap's
            # texttemplate ignores format specs like ":+.1f" and would print the
            # raw float across the tile.
            customdata=np.column_stack(
                [
                    [f"{value:+.2f}%" for value in nodes["change"]],
                    [f"{value:,.0f} M" for value in nodes["value"]],
                    nodes["prices"],
                ]
            ),
            branchvalues="total",
            marker=dict(
                colors=nodes["change"],
                colorscale=[list(step) for step in scale],
                cmin=colour_min,
                cmax=colour_max,
                cmid=0 if config_for_mode["one_sided"] is None else None,
                showscale=True,
                colorbar=dict(
                    title=dict(
                        text=config_for_mode["colourbar"], font=dict(color=theme.MUTED)
                    ),
                    ticksuffix="%",
                    tickfont=dict(color=theme.MUTED),
                    outlinewidth=0,
                    thickness=12,
                ),
                line=dict(color=theme.SURFACE, width=1),
                cornerradius=3,
            ),
            texttemplate="%{label}<br>%{text}",
            textfont=dict(family=theme.FONT_STACK, size=12),
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Market cap  %{customdata[1]}<br>"
                "Change  %{customdata[0]}"
                "%{customdata[2]}"
                "<extra></extra>"
            ),
            tiling=dict(pad=2),
            sort=True,
        )
    )
    figure.update_layout(
        paper_bgcolor=theme.SURFACE,
        plot_bgcolor=theme.SURFACE,
        font=dict(family=theme.FONT_STACK, size=12, color=theme.TEXT_SECONDARY),
        margin=dict(l=8, r=8, t=8, b=8),
        hoverlabel=dict(
            bgcolor=theme.SURFACE,
            bordercolor=theme.BASELINE,
            font=dict(family=theme.FONT_STACK, size=12, color=theme.TEXT_PRIMARY),
        ),
    )

    days = (end - start).days
    median = float(frame["change_pct"].median())

    if one_sided == "down":
        detail = f"median {median:+.1f}% below the window high"
        scale_note = f"colour fixed at -{bound:g}%..0"
    elif one_sided == "up":
        detail = f"median {median:+.1f}% above the window low"
        scale_note = f"colour fixed at 0..+{bound:g}%"
    else:
        advancing = int((frame["change_pct"] > 0).sum())
        detail = f"{advancing} up / {len(frame) - advancing} down"
        scale_note = f"colour fixed at ±{bound:g}%"

    summary = (
        f"{config_for_mode['label']} · {len(frame):,} stocks · "
        f"{start.date()} to {end.date()} ({days}d) · {detail} · {scale_note}"
    )
    return figure, summary
