"""Inspection - selected stocks and up to two indicators on one time axis.

Three encodings run at once, and they carry different things:

* colour  = which stock, so every series for one company matches
* marker  = which fundamental indicator (quarterly, so drawn as points)
* dash    = which price indicator (daily, so drawn as a line)

The second indicator uses the right-hand axis. Two scales on one plot can imply
a relationship that is really just the axes being lined up arbitrarily, so the
legend names every series with the axis it belongs to (L / R) rather than
leaving the reader to infer it.
"""

from __future__ import annotations

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html

from .. import components, data, indicators, theme

PAGE = "inspection"

# Indicator 1 takes the first of each; indicator 2 the second.
MARKER_SYMBOLS = ("circle", "diamond")
LINE_DASHES = ("solid", "dash")


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
                        "the indicator.",
                        className="page-subtitle",
                    ),
                    components.filter_panel(PAGE),
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
                                        value="close",
                                        placeholder="Pick an indicator",
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
                                        value="PE",
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


def _add_series(figure, frame, ticker, column, slot, colour, on_right):
    """One stock's history of one indicator.

    Quarterly fundamentals get a line *and* markers: the line carries the shape
    across four observations a year, the markers show where the reported points
    actually are. Daily price series are dense enough to read as a bare line.
    """
    series = frame.dropna(subset=[column])
    if series.empty:
        return False

    is_fundamental = data.source_of(column) == indicators.SOURCE_FUNDAMENTAL
    axis_tag = "R" if on_right else "L"
    line = dict(color=colour, width=2, dash=LINE_DASHES[slot])

    if is_fundamental:
        mode, marker = (
            "lines+markers",
            dict(
                symbol=MARKER_SYMBOLS[slot],
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
            hovertemplate=(
                f"<b>{ticker}</b>  {column}<br>%{{x|%Y-%m-%d}}  %{{y:.4g}}<extra></extra>"
            ),
        )
    )
    return True


@callback(
    Output("insp-chart", "figure"),
    Output("insp-summary", "children"),
    Input(components.fid("stock", PAGE), "value"),
    Input("insp-ind1", "value"),
    Input("insp-ind2", "value"),
    Input("insp-slider", "value"),
)
def _update_chart(tickers, indicator1, indicator2, slider_value):
    if not tickers:
        return theme.empty_figure("Select one or more stocks to inspect."), ""
    if not indicator1 and not indicator2:
        return theme.empty_figure("Pick at least one indicator."), ""

    start, end = _window(slider_value)
    figure = go.Figure()

    plotted = 0
    for position, ticker in enumerate(tickers):
        colour = theme.colour_for(position) or theme.MUTED
        for slot, column in enumerate((indicator1, indicator2)):
            if not column:
                continue
            history = data.get_history([ticker], (column,), source=data.source_of(column))
            window = history[(history["date"] >= start) & (history["date"] <= end)]
            if _add_series(figure, window, ticker, column, slot, colour, on_right=slot == 1):
                plotted += 1

    if not plotted:
        return theme.empty_figure("No data for this selection in this period."), ""

    figure.update_layout(
        theme.base_layout(
            hovermode="closest",
            yaxis=dict(
                title=dict(
                    text=f"{indicator1} (left)" if indicator1 else "",
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
                    text=f"{indicator2} (right)" if indicator2 else "",
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

    note = f"{plotted} series · {start.date()} to {end.date()}"
    if len(tickers) > theme.MAX_COLOURED_SERIES:
        note += f" · only the first {theme.MAX_COLOURED_SERIES} stocks get a colour"
    return figure, note
