"""Inspection - selected stocks and their indicators on one time axis.

Three encodings run at once, and they carry different things:

* colour  = which stock, so every series for one company matches
* marker  = which fundamental indicator (quarterly, so drawn as points)
* dash    = which indicator of the same kind: the first price indicator is
            solid, the second dashed, and so on; fundamentals likewise

Fundamentals are dated by the day their numbers became public, not by the
period they report, so the chart shows only what an investor could have known
on each day - no look-ahead.

Indicator 1 picks go on the left axis, Indicator 2 picks on the right. Two scales on one plot can imply
a relationship that is really just the axes being lined up arbitrarily, so the
legend names every series with the axis it belongs to (L / R) rather than
leaving the reader to infer it.
"""

from __future__ import annotations

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dash_table, dcc, html

from .. import components, config, data, indicators, theme

PAGE = "inspection"

# The n-th indicator of a kind (price or fundamental) takes the n-th of each.
MARKER_SYMBOLS = ("circle", "diamond", "square", "triangle-up", "x", "star")
LINE_DASHES = ("solid", "dash", "dot", "dashdot", "longdash", "longdashdot")

X_PADDING = 0.02  # share of the plotted span left empty at each end


def _slider_marks(months: pd.DatetimeIndex) -> dict:
    return {
        i: {"label": str(months[i].year), "style": {"color": theme.MUTED, "fontSize": "11px"}}
        for i in range(0, len(months), 60)
    }


def layout():
    months = data.get_month_grid()
    options = data.get_indicator_options()

    return html.Div(
        [
            components.nav_bar("/inspection"),
            html.Main(
                [
                    html.H1("Inspection", className="page-title"),
                    html.P(
                        "Track indicators through time for the stocks you pick. "
                        "Colour identifies the stock; markers and dashes identify "
                        "the indicator. Fundamentals are plotted on the day they "
                        "became public and held until the next release.",
                        className="page-subtitle",
                    ),
                    components.filter_panel(PAGE, portfolio_button=True),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label(
                                        "Indicator 1 · left axis", className="field-label"
                                    ),
                                    dcc.Dropdown(
                                        id="insp-ind1",
                                        options=options,
                                        value=["close"],
                                        multi=True,
                                        placeholder="Pick indicators",
                                    ),
                                ],
                                className="field",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Indicator 2 · right axis", className="field-label"
                                    ),
                                    dcc.Dropdown(
                                        id="insp-ind2",
                                        options=options,
                                        value=["PE"],
                                        multi=True,
                                        placeholder="Optional",
                                    ),
                                ],
                                className="field",
                            ),
                        ],
                        className="filter-panel",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Period", className="field-label"),
                                    dcc.RangeSlider(
                                        id="insp-slider",
                                        min=0,
                                        max=len(months) - 1,
                                        step=1,
                                        value=[0, len(months) - 1],
                                        marks=_slider_marks(months),
                                        tooltip={"placement": "bottom"},
                                        allowCross=False,
                                    ),
                                ],
                                className="field field--wide",
                            )
                        ],
                        className="filter-panel",
                    ),
                    html.Div(id="insp-summary", className="summary"),
                    dcc.Loading(
                        dcc.Graph(
                            id="insp-chart",
                            style={"height": "64vh"},
                            config={"displaylogo": False, "scrollZoom": True},
                        ),
                        type="default",
                    ),
                    html.Div(id="insp-stocks"),
                ],
                className="page",
            ),
        ]
    )


dash.register_page(__name__, path="/inspection", name="Inspection", order=5, layout=layout)


def _window(slider_value) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Slider positions to dates; the whole history by default."""
    months = data.get_month_grid()
    if not slider_value:
        return months[0], pd.Timestamp(data.get_meta()["price_date_max"])

    low, high = slider_value
    start = months[max(0, min(int(low), len(months) - 1))]
    if int(high) >= len(months) - 1:
        end = pd.Timestamp(data.get_meta()["price_date_max"])
    else:
        end = months[int(high) + 1] - pd.Timedelta(days=1)
    return start, end


def _as_list(value) -> list[str]:
    if not value:
        return []
    return [value] if isinstance(value, str) else list(value)


def _add_series(figure, frame, ticker, column, rank, colour, on_right):
    """One stock's history of one indicator.

    Quarterly fundamentals get a step line *and* markers: each marker is a
    release, and the value holds flat until the next one - a sloped line between
    releases would show a number nobody knew yet. Daily price series are dense
    enough to read as a bare line. `rank` is the indicator's position among
    those of its kind, so the first price and the first fundamental are solid.
    """
    series = frame.dropna(subset=[column])
    if series.empty:
        return False

    is_fundamental = data.source_of(column) == indicators.SOURCE_FUNDAMENTAL
    axis_tag = "R" if on_right else "L"
    line = dict(color=colour, width=2, dash=LINE_DASHES[rank % len(LINE_DASHES)])
    hover = f"<b>{ticker}</b>  {column}<br>%{{x|%Y-%m-%d}}  %{{y:.4g}}"
    customdata = None

    if is_fundamental:
        line["shape"] = "hv"
        hover = (
            f"<b>{ticker}</b><br>{column}: %{{y:.4g}}"
            "<br>public %{x|%Y-%m-%d}"
            "<br>quarter ended %{customdata|%Y-%m-%d}"
        )
        customdata = series["period_end"]
        mode, marker = (
            "lines+markers",
            dict(
                symbol=MARKER_SYMBOLS[rank % len(MARKER_SYMBOLS)],
                size=7,
                color=colour,
                line=dict(color=theme.SURFACE, width=1),
            ),
        )
    else:
        mode, marker = "lines", None

    figure.add_trace(
        go.Scatter(
            x=series["date"],
            y=series[column],
            name=f"{ticker} · {column} ({axis_tag})",
            mode=mode,
            line=line,
            marker=marker,
            opacity=theme.SERIES_OPACITY,
            yaxis="y2" if on_right else "y",
            customdata=customdata,
            hovertemplate=hover + "<extra></extra>",
        )
    )
    return True


def _padded_range(figure) -> list[pd.Timestamp]:
    """First to last plotted date, widened so the end markers clear the frame."""
    dates = pd.to_datetime(pd.concat([pd.Series(trace.x) for trace in figure.data]))
    first, last = dates.min(), dates.max()
    pad = max((last - first) * X_PADDING, pd.Timedelta(days=1))
    return [first - pad, last + pad]


@callback(
    Output("insp-chart", "figure"),
    Output("insp-summary", "children"),
    Input(components.fid("stock", PAGE), "value"),
    Input("insp-ind1", "value"),
    Input("insp-ind2", "value"),
    Input("insp-slider", "value"),
)
def _update_chart(tickers, indicator1, indicator2, slider_value):
    left = _as_list(indicator1)
    right = [c for c in _as_list(indicator2) if c not in left]
    if not tickers:
        return theme.empty_figure("Select one or more stocks to inspect."), ""
    if not left and not right:
        return theme.empty_figure("Pick at least one indicator."), ""

    start, end = _window(slider_value)
    figure = go.Figure()

    picks, seen = [], {}  # (column, on_right, rank among indicators of its kind)
    for column, on_right in [(c, False) for c in left] + [(c, True) for c in right]:
        kind = data.source_of(column)
        picks.append((column, on_right, seen.get(kind, 0)))
        seen[kind] = seen.get(kind, 0) + 1

    plotted = 0
    for position, ticker in enumerate(tickers):
        colour = theme.colour_for(position) or theme.MUTED
        for column, on_right, rank in picks:
            history = data.get_history(
                [ticker], (column,), source=data.source_of(column), point_in_time=True
            )
            window = history[(history["date"] >= start) & (history["date"] <= end)]
            if _add_series(figure, window, ticker, column, rank, colour, on_right):
                plotted += 1

    if not plotted:
        return theme.empty_figure("No data for this selection in this period."), ""

    figure.update_layout(
        theme.base_layout(
            hovermode="closest",
            yaxis=dict(
                title=dict(
                    text=f"{', '.join(left)} (left)" if left else "",
                    font=dict(color=theme.MUTED),
                ),
                showgrid=True,
                gridcolor=theme.GRIDLINE,
                linecolor=theme.BASELINE,
                tickfont=dict(color=theme.MUTED),
                hoverformat=".4g",
                zeroline=False,
            ),
            yaxis2=dict(
                title=dict(
                    text=f"{', '.join(right)} (right)" if right else "",
                    font=dict(color=theme.MUTED),
                ),
                overlaying="y",
                side="right",
                showgrid=False,
                linecolor=theme.BASELINE,
                tickfont=dict(color=theme.MUTED),
                hoverformat=".4g",
                zeroline=False,
            ),
        )
    )
    figure.update_xaxes(range=_padded_range(figure))

    note = f"{plotted} series · {start.date()} to {end.date()}"
    if len(tickers) > theme.MAX_COLOURED_SERIES:
        note += f" · only the first {theme.MAX_COLOURED_SERIES} stocks get a colour"
    return figure, note


@callback(
    Output("insp-stocks", "children"),
    Input(components.fid("stock", PAGE), "value"),
)
def _update_stocks_table(tickers):
    """Sector and industry of the selected stocks, each ticker in its chart colour."""
    if not tickers:
        return None
    stocks = data.get_stocks().set_index("ticker")
    rows = [
        {
            "Ticker": t,
            config.SECTOR_COL: stocks.at[t, config.SECTOR_COL],
            config.INDUSTRY_COL: stocks.at[t, config.INDUSTRY_COL],
        }
        for t in tickers
        if t in stocks.index
    ]
    colours = [
        {
            "if": {"row_index": i, "column_id": "Ticker"},
            "color": theme.colour_for(i) or theme.MUTED,
            "fontWeight": "600",
        }
        for i in range(len(rows))
    ]
    return dash_table.DataTable(
        columns=[{"name": c, "id": c} for c in ("Ticker", config.SECTOR_COL, config.INDUSTRY_COL)],
        data=rows,
        style_table={"overflowX": "auto", "marginTop": "16px"},
        style_cell={
            "fontFamily": "var(--font-mono)",
            "fontSize": "13px",
            "padding": "6px 10px",
            "textAlign": "left",
        },
        style_header={"fontWeight": "600", "backgroundColor": "var(--surface-2)"},
        style_data_conditional=colours,
    )
