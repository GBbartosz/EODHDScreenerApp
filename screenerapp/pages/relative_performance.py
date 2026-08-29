"""Relative performance - price change from a common starting point, in percent.

Rebasing every selected stock to 0% at the start of the window is what makes the
comparison honest: a 3000-dollar share and a 5-dollar share sit on the same axis
without either one flattening the other.

The slider and the date pickers are two views of the same window. Whichever one
you touch updates the other, and changing the stock selection resets the window
to the span the selected stocks actually share.
"""

from __future__ import annotations

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

from .. import components, data, theme

PAGE = "relative-performance"
DATE_FMT = "%Y-%m-%d"

# Growth multiples that get a gridline on the log scale. Labelled as percent
# change so both scales read in the same units.
LOG_TICK_RATIOS = (
    0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.25, 1.5,
    2, 3, 5, 10, 20, 30, 50, 100, 200,
)


def _months() -> pd.DatetimeIndex:
    """Month grid backing the slider - shared with the inspection page."""
    return data.get_month_grid()


def _to_index(value: pd.Timestamp) -> int:
    months = _months()
    return int(min(max(months.searchsorted(value, side="right") - 1, 0), len(months) - 1))


def _to_date(index: int, *, upper: bool) -> pd.Timestamp:
    """Slider index back to a date; the top of the range means "through the end"."""
    months = _months()
    index = int(min(max(index, 0), len(months) - 1))
    if upper:
        if index >= len(months) - 1:
            return pd.Timestamp(data.get_meta()["price_date_max"])
        return months[index + 1] - pd.Timedelta(days=1)
    return months[index]


def _default_window(tickers: list[str] | None) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The span the selected stocks share.

    Overlap, not union: rebasing needs a date every selected stock actually
    traded on, otherwise the newest listing would start the chart at a point the
    others have no price for. Falls back to the union if there is no overlap.
    """
    meta = data.get_meta()
    full = (pd.Timestamp(meta["price_date_min"]), pd.Timestamp(meta["price_date_max"]))
    if not tickers:
        return full

    stocks = data.get_stocks()
    rows = stocks[stocks["ticker"].isin(tickers)]
    if rows.empty:
        return full

    start = rows["first_price_date"].max()
    end = rows["last_price_date"].min()
    if start >= end:  # disjoint listings - show everything and let the gap speak
        return rows["first_price_date"].min(), rows["last_price_date"].max()
    return start, end


def layout():
    months = _months()
    marks = {
        i: {"label": str(months[i].year), "style": {"color": theme.MUTED, "fontSize": "11px"}}
        for i in range(0, len(months), 60)
    }

    return html.Div(
        [
            components.nav_bar("/relative-performance"),
            html.Main(
                [
                    html.H1("Relative Performance", className="page-title"),
                    html.P(
                        "Price change from the start of the window, so stocks at "
                        "different price levels stay comparable.",
                        className="page-subtitle",
                    ),
                    components.filter_panel(PAGE),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Period", className="field-label"),
                                    dcc.RangeSlider(
                                        id="rp-slider",
                                        min=0,
                                        max=len(months) - 1,
                                        step=1,
                                        value=[0, len(months) - 1],
                                        marks=marks,
                                        tooltip={"placement": "bottom"},
                                        allowCross=False,
                                    ),
                                ],
                                className="field field--wide",
                            ),
                            html.Div(
                                [
                                    html.Label("Exact dates", className="field-label"),
                                    dcc.DatePickerRange(
                                        id="rp-dates",
                                        min_date_allowed=months[0],
                                        max_date_allowed=data.get_meta()["price_date_max"],
                                        start_date=months[0],
                                        end_date=data.get_meta()["price_date_max"],
                                        display_format="YYYY-MM-DD",
                                    ),
                                ],
                                className="field field--narrow",
                            ),
                            html.Div(
                                [
                                    html.Label("Scale", className="field-label"),
                                    dcc.RadioItems(
                                        id="rp-scale",
                                        options=[
                                            {"label": "Linear", "value": "linear"},
                                            {"label": "Log", "value": "log"},
                                        ],
                                        value="linear",
                                        className="checklist",
                                    ),
                                ],
                                className="field field--narrow",
                            ),
                        ],
                        className="filter-panel",
                    ),
                    html.Div(id="rp-summary", className="summary"),
                    dcc.Loading(
                        dcc.Graph(
                            id="rp-chart",
                            style={"height": "62vh"},
                            config={"displaylogo": False, "scrollZoom": True},
                        ),
                        type="default",
                    ),
                ],
                className="page",
            ),
        ]
    )


# See the note in home.py: registration happens after `layout` exists so it can
# be passed explicitly.
dash.register_page(
    __name__,
    path="/relative-performance",
    name="Relative Performance",
    order=2,
    layout=layout,
)


@callback(
    Output("rp-slider", "value"),
    Output("rp-dates", "start_date"),
    Output("rp-dates", "end_date"),
    Input("rp-slider", "value"),
    Input("rp-dates", "start_date"),
    Input("rp-dates", "end_date"),
    Input(components.fid("stock", PAGE), "value"),
    prevent_initial_call=True,
)
def _sync_window(slider_value, start_date, end_date, tickers):
    """Keep slider and date pickers showing the same window.

    Each branch returns no_update for whichever control the user just moved,
    which is what stops the two from triggering each other in a loop.
    """
    trigger = ctx.triggered_id

    if trigger == "rp-slider":
        low, high = slider_value
        return no_update, _to_date(low, upper=False), _to_date(high, upper=True)

    if trigger == "rp-dates":
        start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
        return [_to_index(start), _to_index(end)], no_update, no_update

    # Stock selection changed - reset to the span those stocks share.
    start, end = _default_window(tickers)
    return [_to_index(start), _to_index(end)], start, end


def _y_axis(scale: str, low: float, high: float) -> dict:
    """Axis config for the chosen scale.

    Both scales are labelled in percent change. On the log scale the plotted
    value is the growth multiple - a single stock up 3000% would otherwise
    squash everything else onto the zero line - and the ticks convert those
    multiples back to percentages so the two scales read the same way.
    """
    axis = dict(
        showgrid=True,
        gridcolor=theme.GRIDLINE,
        linecolor=theme.BASELINE,
        tickfont=dict(color=theme.MUTED),
        title=dict(text="Change from start of window", font=dict(color=theme.MUTED)),
        # Unified hover falls back to the axis format for anything the trace
        # template doesn't spell out, so pin it here too - otherwise stray
        # full-precision values turn up in the hover box.
        hoverformat=".1f",
    )

    if scale == "log":
        ratios = [r for r in LOG_TICK_RATIOS if low / 1.5 <= r <= high * 1.5]
        axis.update(
            type="log",
            zeroline=False,
            tickvals=ratios,
            ticktext=[f"{(r - 1) * 100:+.0f}%" for r in ratios],
        )
    else:
        axis.update(
            zeroline=True,
            zerolinecolor=theme.BASELINE,
            zerolinewidth=1,
            ticksuffix="%",
        )
    return axis


@callback(
    Output("rp-chart", "figure"),
    Output("rp-summary", "children"),
    Input("rp-dates", "start_date"),
    Input("rp-dates", "end_date"),
    Input(components.fid("stock", PAGE), "value"),
    Input("rp-scale", "value"),
    State(components.fid("sector", PAGE), "value"),
    State(components.fid("industry", PAGE), "value"),
)
def _update_chart(start_date, end_date, tickers, scale, sectors, industries):
    if not tickers:
        hint = "Select one or more stocks to compare."
        if sectors or industries:
            hint = "Select stocks from the filtered list to compare."
        return theme.empty_figure(hint), ""

    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    history = data.get_history(tickers, ("close",))
    window = history[(history["date"] >= start) & (history["date"] <= end)]

    figure = go.Figure()

    plotted, skipped = 0, []
    # Big selections stay responsive on WebGL; small ones look crisper on SVG.
    total_points = len(window)
    trace_type = go.Scattergl if total_points > 40_000 else go.Scatter

    low, high = 1.0, 1.0

    for position, ticker in enumerate(tickers):
        series = window[window["ticker"] == ticker].dropna(subset=["close"])
        series = series[series["close"] > 0]
        if series.empty:
            skipped.append(ticker)
            continue

        base = series["close"].iloc[0]
        if not base:
            skipped.append(ticker)
            continue

        ratio = series["close"] / base
        percent = (ratio - 1) * 100
        low, high = min(low, ratio.min()), max(high, ratio.max())

        colour = theme.colour_for(position)
        is_context = colour is None

        figure.add_trace(
            trace_type(
                x=series["date"],
                y=ratio if scale == "log" else percent,
                # Column vector, not a flat array: the ":+.1f" format spec is
                # only honoured with explicit indexing (customdata[0]), and a
                # 1-D customdata silently renders at full precision instead.
                customdata=percent.to_numpy()[:, None],
                name=ticker,
                mode="lines",
                line=dict(
                    color=colour or theme.MUTED,
                    width=2 if not is_context else 1,
                ),
                opacity=theme.CONTEXT_OPACITY if is_context else theme.SERIES_OPACITY,
                showlegend=not is_context,
                hovertemplate=f"<b>{ticker}</b>  %{{customdata[0]:+.1f}}%<extra></extra>",
            )
        )
        plotted += 1

    if not plotted:
        return theme.empty_figure("No price data for these stocks in this window."), ""

    figure.update_layout(theme.base_layout(yaxis=_y_axis(scale, low, high)))

    parts = [
        f"{plotted} stocks · {start.date()} to {end.date()}",
    ]
    if plotted > theme.MAX_COLOURED_SERIES:
        parts.append(
            f"first {theme.MAX_COLOURED_SERIES} coloured, "
            f"{plotted - theme.MAX_COLOURED_SERIES} shown as context"
        )
    if skipped:
        parts.append(f"no data in window: {', '.join(skipped[:6])}")

    return figure, " · ".join(parts)
