"""Indicator distribution - where a stock sits relative to the market.

One indicator gives a histogram of the whole market, with the selected sectors
or industries drawn on the same bin edges behind it and the selected stocks
marked where they fall. Two indicators turn that into a density map of the
market with the selection scattered on top.

Both histograms are drawn as a share of their own group rather than raw counts.
Forty stocks in an industry against seven hundred in the market would otherwise
flatten to nothing, and the question the page answers is about shape, not size.

Values outside the range boxes are clipped into the end bins rather than
dropped, so the counts still add up to the whole group.
"""

from __future__ import annotations

import dash
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html

from .. import components, config, data, theme

PAGE = "indicator-distribution"

DEFAULT_BINS = 100
# Market takes palette slot 1 and the sector/industry subset slot 2, so
# individual stocks start after them.
STOCK_SLOT_OFFSET = 2


def _indicator_controls(index: int) -> html.Div:
    """Bins and range boxes for one indicator."""
    return html.Div(
        [
            html.Div(
                [
                    html.Label(f"Bins {index}", className="field-label"),
                    dcc.Input(
                        id=f"idst-bins{index}",
                        type="number",
                        value=DEFAULT_BINS,
                        min=2,
                        max=500,
                        step=1,
                        debounce=True,
                        className="number-input",
                    ),
                ],
                className="field field--narrow",
            ),
            html.Div(
                [
                    html.Label(f"Min {index}", className="field-label"),
                    dcc.Input(
                        id=f"idst-min{index}",
                        type="number",
                        debounce=True,
                        className="number-input",
                    ),
                ],
                className="field field--narrow",
            ),
            html.Div(
                [
                    html.Label(f"Max {index}", className="field-label"),
                    dcc.Input(
                        id=f"idst-max{index}",
                        type="number",
                        debounce=True,
                        className="number-input",
                    ),
                ],
                className="field field--narrow",
            ),
        ],
        className="filter-panel filter-panel--nested",
    )


def layout():
    dates = data.get_trading_dates()
    options = data.get_indicator_options()

    return html.Div(
        [
            components.nav_bar("/indicator-distribution"),
            html.Main(
                [
                    html.H1("Indicator Distribution", className="page-title"),
                    html.P(
                        "Where selected stocks sit within the market's distribution "
                        "of an indicator, and within their sector or industry.",
                        className="page-subtitle",
                    ),
                    components.filter_panel(PAGE),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Date", className="field-label"),
                                    dcc.DatePickerSingle(
                                        id="idst-date",
                                        min_date_allowed=dates[0],
                                        max_date_allowed=dates[-1],
                                        date=dates[-1],
                                        display_format="YYYY-MM-DD",
                                    ),
                                ],
                                className="field field--narrow",
                            ),
                            html.Div(
                                [
                                    html.Label("Indicator 1", className="field-label"),
                                    dcc.Dropdown(
                                        id="idst-ind1",
                                        options=options,
                                        value="PE",
                                        placeholder="Pick an indicator",
                                    ),
                                ],
                                className="field",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Indicator 2 (optional)", className="field-label"
                                    ),
                                    dcc.Dropdown(
                                        id="idst-ind2",
                                        options=options,
                                        value=None,
                                        placeholder="Leave empty for a 1D histogram",
                                    ),
                                ],
                                className="field",
                            ),
                        ],
                        className="filter-panel",
                    ),
                    _indicator_controls(1),
                    _indicator_controls(2),
                    html.Div(id="idst-summary", className="summary"),
                    dcc.Loading(
                        dcc.Graph(
                            id="idst-chart",
                            style={"height": "62vh"},
                            config={"displaylogo": False},
                        ),
                        type="default",
                    ),
                ],
                className="page",
            ),
        ]
    )


dash.register_page(
    __name__,
    path="/indicator-distribution",
    name="Indicator Distribution",
    order=4,
    layout=layout,
)


def _default_range(values: pd.Series) -> tuple[float | None, float | None]:
    """Full minimum up to the 99th percentile.

    Financial indicators mostly have a natural floor but no ceiling - a single
    stock on a 900x earnings multiple would otherwise push the whole market into
    the first bin.
    """
    clean = values.dropna()
    if clean.empty:
        return None, None
    return float(clean.min()), float(clean.quantile(0.99))


@callback(
    Output("idst-min1", "value"),
    Output("idst-max1", "value"),
    Output("idst-min2", "value"),
    Output("idst-max2", "value"),
    Input("idst-ind1", "value"),
    Input("idst-ind2", "value"),
    Input("idst-date", "date"),
)
def _reset_ranges(indicator1, indicator2, date):
    """Repopulate the range boxes whenever the indicator or date changes."""
    stamp = data.snap_to_trading_date(date)
    wanted = [c for c in (indicator1, indicator2) if c]
    if not wanted:
        return None, None, None, None

    frame = data.get_cross_section(stamp, wanted)
    low1, high1 = _default_range(frame[indicator1]) if indicator1 else (None, None)
    low2, high2 = _default_range(frame[indicator2]) if indicator2 else (None, None)
    return low1, high1, low2, high2


def _prepare(frame: pd.DataFrame, column: str, low, high) -> pd.DataFrame:
    """Drop rows with no value, then clip the rest into the chosen range."""
    out = frame.dropna(subset=[column]).copy()
    if low is not None and high is not None and high > low:
        out[column] = out[column].clip(float(low), float(high))
    return out


def _subset_mask(frame: pd.DataFrame, sectors, industries) -> pd.Series | None:
    """Rows matching the sector/industry selection, or None when nothing is set."""
    if not sectors and not industries:
        return None
    mask = pd.Series(True, index=frame.index)
    if sectors:
        mask &= frame[config.SECTOR_COL].isin(sectors)
    if industries:
        mask &= frame[config.INDUSTRY_COL].isin(industries)
    return mask


def _share_histogram(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    counts, _ = np.histogram(values, bins=edges)
    total = counts.sum()
    return counts / total * 100 if total else counts.astype(float)


def _one_dimensional(frame, column, bins, low, high, sectors, industries, tickers):
    market = _prepare(frame, column, low, high)
    if market.empty:
        return theme.empty_figure("No values for this indicator on this date."), ""

    lo = float(low) if low is not None else float(market[column].min())
    hi = float(high) if high is not None else float(market[column].max())
    if not hi > lo:
        hi = lo + 1.0
    edges = np.linspace(lo, hi, int(bins) + 1)
    centres = (edges[:-1] + edges[1:]) / 2
    width = edges[1] - edges[0]

    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=centres,
            y=_share_histogram(market[column].to_numpy(), edges),
            width=width,
            name=f"Market ({len(market)})",
            marker=dict(color=theme.SERIES[0], line=dict(width=0)),
            opacity=0.55,
            hovertemplate="Market  %{y:.1f}% of group<br>%{x:.4g}<extra></extra>",
        )
    )

    mask = _subset_mask(market, sectors, industries)
    if mask is not None and mask.any():
        subset = market[mask]
        figure.add_trace(
            go.Bar(
                x=centres,
                y=_share_histogram(subset[column].to_numpy(), edges),
                width=width,
                name=f"Selection ({len(subset)})",
                marker=dict(color=theme.SERIES[1], line=dict(width=0)),
                opacity=0.55,
                hovertemplate="Selection  %{y:.1f}% of group<br>%{x:.4g}<extra></extra>",
            )
        )

    # Selected stocks as vertical rules, so a stock reads against both shapes.
    marked, missing = 0, []
    for position, ticker in enumerate(tickers or []):
        row = market[market["ticker"] == ticker]
        if row.empty:
            missing.append(ticker)
            continue
        value = float(row[column].iloc[0])
        colour = theme.colour_for(position + STOCK_SLOT_OFFSET) or theme.MUTED
        figure.add_trace(
            go.Scatter(
                x=[value, value],
                y=[0, 100],
                mode="lines",
                name=f"{ticker}  {value:,.4g}",
                line=dict(color=colour, width=2),
                hovertemplate=f"<b>{ticker}</b>  {value:,.4g}<extra></extra>",
            )
        )
        marked += 1

    figure.update_layout(
        theme.base_layout(
            barmode="overlay",
            hovermode="closest",
            xaxis=dict(
                title=dict(text=column, font=dict(color=theme.MUTED)),
                showgrid=False,
                linecolor=theme.BASELINE,
                tickfont=dict(color=theme.MUTED),
                zeroline=False,
            ),
            yaxis=dict(
                title=dict(text="% of group", font=dict(color=theme.MUTED)),
                showgrid=True,
                gridcolor=theme.GRIDLINE,
                linecolor=theme.BASELINE,
                ticksuffix="%",
                tickfont=dict(color=theme.MUTED),
                zeroline=False,
                rangemode="tozero",
            ),
        )
    )
    # The stock rules are drawn to y=100; keep the axis on the histogram.
    tallest = max(
        (max(trace.y) for trace in figure.data if isinstance(trace, go.Bar) and len(trace.y)),
        default=1.0,
    )
    figure.update_yaxes(range=[0, tallest * 1.1])

    note = f"{len(market):,} stocks in market · {marked} marked"
    if missing:
        note += f" · no value: {', '.join(missing[:6])}"
    return figure, note


def _two_dimensional(
    frame, column_x, column_y, bins_x, bins_y, range_x, range_y, sectors, industries, tickers
):
    market = _prepare(frame, column_x, *range_x)
    market = _prepare(market, column_y, *range_y)
    if market.empty:
        return theme.empty_figure("No values for this pair on this date."), ""

    figure = go.Figure()
    figure.add_trace(
        go.Histogram2dContour(
            x=market[column_x],
            y=market[column_y],
            nbinsx=int(bins_x),
            nbinsy=int(bins_y),
            colorscale=[list(step) for step in theme.SEQUENTIAL_BLUE],
            contours=dict(coloring="fill"),
            ncontours=14,
            showscale=True,
            colorbar=dict(
                title=dict(text="Stocks", font=dict(color=theme.MUTED)),
                tickfont=dict(color=theme.MUTED),
                outlinewidth=0,
                thickness=12,
            ),
            hovertemplate=f"{column_x}  %{{x:.4g}}<br>{column_y}  %{{y:.4g}}"
            "<br>%{z} stocks<extra></extra>",
            name=f"Market ({len(market)})",
            showlegend=True,
        )
    )

    mask = _subset_mask(market, sectors, industries)
    if mask is not None and mask.any():
        subset = market[mask]
        figure.add_trace(
            go.Scatter(
                x=subset[column_x],
                y=subset[column_y],
                mode="markers",
                name=f"Selection ({len(subset)})",
                marker=dict(
                    color=theme.SERIES[1],
                    size=8,
                    line=dict(color=theme.SURFACE, width=1),
                ),
                opacity=0.75,
                customdata=subset[["ticker"]].to_numpy(),
                hovertemplate="<b>%{customdata[0]}</b><br>"
                f"{column_x}  %{{x:.4g}}<br>{column_y}  %{{y:.4g}}<extra></extra>",
            )
        )

    marked, missing = 0, []
    for position, ticker in enumerate(tickers or []):
        row = market[market["ticker"] == ticker]
        if row.empty:
            missing.append(ticker)
            continue
        colour = theme.colour_for(position + STOCK_SLOT_OFFSET) or theme.MUTED
        figure.add_trace(
            go.Scatter(
                x=[float(row[column_x].iloc[0])],
                y=[float(row[column_y].iloc[0])],
                mode="markers+text",
                name=ticker,
                text=[ticker],
                textposition="top center",
                textfont=dict(family=theme.FONT_STACK, size=11, color=theme.TEXT_PRIMARY),
                marker=dict(
                    color=colour, size=13, line=dict(color=theme.SURFACE, width=2)
                ),
                hovertemplate=f"<b>{ticker}</b><br>"
                f"{column_x}  %{{x:.4g}}<br>{column_y}  %{{y:.4g}}<extra></extra>",
            )
        )
        marked += 1

    figure.update_layout(
        theme.base_layout(
            hovermode="closest",
            xaxis=dict(
                title=dict(text=column_x, font=dict(color=theme.MUTED)),
                showgrid=True,
                gridcolor=theme.GRIDLINE,
                linecolor=theme.BASELINE,
                tickfont=dict(color=theme.MUTED),
                zeroline=False,
            ),
            yaxis=dict(
                title=dict(text=column_y, font=dict(color=theme.MUTED)),
                showgrid=True,
                gridcolor=theme.GRIDLINE,
                linecolor=theme.BASELINE,
                tickfont=dict(color=theme.MUTED),
                zeroline=False,
            ),
        )
    )

    note = f"{len(market):,} stocks in market · {marked} marked"
    if missing:
        note += f" · no value: {', '.join(missing[:6])}"
    return figure, note


@callback(
    Output("idst-chart", "figure"),
    Output("idst-summary", "children"),
    Input("idst-ind1", "value"),
    Input("idst-ind2", "value"),
    Input("idst-bins1", "value"),
    Input("idst-bins2", "value"),
    Input("idst-min1", "value"),
    Input("idst-max1", "value"),
    Input("idst-min2", "value"),
    Input("idst-max2", "value"),
    Input("idst-date", "date"),
    Input(components.fid("sector", PAGE), "value"),
    Input(components.fid("industry", PAGE), "value"),
    Input(components.fid("stock", PAGE), "value"),
)
def _update_chart(
    indicator1,
    indicator2,
    bins1,
    bins2,
    min1,
    max1,
    min2,
    max2,
    date,
    sectors,
    industries,
    tickers,
):
    if not indicator1:
        return theme.empty_figure("Pick an indicator to see its distribution."), ""

    stamp = data.snap_to_trading_date(date)
    wanted = [indicator1] + ([indicator2] if indicator2 else [])
    frame = data.get_cross_section(stamp, wanted)

    bins1 = bins1 or DEFAULT_BINS
    bins2 = bins2 or DEFAULT_BINS

    if indicator2:
        figure, note = _two_dimensional(
            frame, indicator1, indicator2, bins1, bins2,
            (min1, max1), (min2, max2), sectors, industries, tickers,
        )
    else:
        figure, note = _one_dimensional(
            frame, indicator1, bins1, min1, max1, sectors, industries, tickers
        )

    return figure, f"{stamp.date()} · {note}"
