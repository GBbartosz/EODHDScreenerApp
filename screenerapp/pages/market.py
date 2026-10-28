"""Market - buy-and-hold indexes of sectors and industries, from 0% at the window start.

Each button toggles one group's index on the chart. How the index is built
(market cap or equal weight, stocks joining and leaving) is in group_index.py.
Every plotted index gets a table of its stocks underneath, headed by its line
colour, so the tables double as the chart's legend.

The period controls work as on the relative performance page: the slider and
the date pickers are two views of the same window.
"""

from __future__ import annotations

import functools

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback, ctx, dash_table, dcc, html, no_update
from dash.dash_table.Format import Format, Group, Scheme, Sign

from .. import components, config, data, group_index, theme
from .relative_performance import _months, _to_date, _to_index, _y_axis

SECTOR, INDUSTRY = "sector", "industry"

# Not real sectors: tickers the data could not classify. Listed after the rest.
CATCH_ALL_SECTORS = ("Other", "Unclassified")

METHOD_LABELS = {group_index.CAP: "market cap weighted", group_index.EQUAL: "equally weighted"}


# Shown under the tables. Keep in step with group_index.py.
METHOD_NOTES = r"""
## How the indexes are calculated

Both indexes are a portfolio **bought on the first trading day of the window and then
held**. Its value $V$ starts at 1, and the chart shows $(V_t - 1) \times 100\%$, so every
index starts at 0%. Prices $P_{i,t}$ are total-return closes in USD: dividends are
reinvested in the stock that paid them, and foreign stocks are converted at the day's rate.

### Market cap weighted

On the start date each stock gets its share of the group's market cap $MC$:

$$w_i = \frac{MC_{i,0}}{\sum_j MC_{j,0}} \qquad u_i = \frac{w_i}{P_{i,0}} \qquad V_t = \sum_i u_i \, P_{i,t} = \sum_i w_i \frac{P_{i,t}}{P_{i,0}}$$

$u_i$ is the number of units bought, and it stays fixed. A stock's weight on day $t$ is
$w_{i,t} = u_i P_{i,t} / V_t$, so it moves with the price. Market cap is shares × price,
so holding these units follows the group's cap-weighted index for as long as share counts
don't change. A stock with no market cap on the start date joins on the first day it has one.

### Equally weighted

The same formulas with $w_i = 1/N$ on the start date. Nothing is rebalanced, so the
weights stay equal only on the first day. After that, the stocks that rose carry more weight.

*Example:* two stocks at 50% each. A doubles and B is flat:
$V = 0.5 \cdot 2 + 0.5 \cdot 1 = 1.5$, so the index is +50%, and the weights are now
A 67%, B 33%.

### When a stock leaves (delisted, or its prices end)

On the first day it has no price, the stock is sold at its last price. The money goes to
the remaining stocks $S$ in proportion to what each holds, so the index carries on at
their combined return:

$$V_t = V_{t-1} \times \frac{\sum_{i \in S} u_i P_{i,t}}{\sum_{i \in S} u_i P_{i,t-1}}$$

* The stock's gain or loss up to its last price stays in the index; leaving is **not**
  counted as −100%.
* The remaining stocks keep their weights relative to each other.
  *Example:* A 50%, B 30%, C 20%. C leaves, so A becomes 50/80 = 62.5% and B 37.5%.
* If the real payout differed from the last price (a takeover premium paid later, or a
  bankruptcy that kept trading over the counter), the index does not see it.

### When a stock joins (listed during the window, or its first market cap)

It is bought at its weight on the day it joins, $t$. The money comes from selling the
same fraction of every current holding:

$$w_{new} = \frac{MC_{new,t}}{\sum_{j} MC_{j,t}} \ \text{(market cap, the newcomer included)} \qquad w_{new} = \frac{1}{N_t} \ \text{(equal, } N_t \text{ counting it)}$$

$$u_i \leftarrow u_i \,(1 - w_{new}) \qquad u_{new} = \frac{w_{new} \, V_t}{P_{new,t}}$$

The index value does not jump on that day; only the mix changes.
*Example:* equally weighted, 3 stocks worth $V = 1.2$. A fourth joins with
$1.2 / 4 = 0.3$, and each of the other three is cut by a quarter to pay for it.

### Limits of the data

* Members are the stocks in the sector or industry **today**. Past reclassifications are
  not known.
* Delisted stocks without a sector sit in "Other", so they are missing from their real
  sectors. That makes those sector histories look better than they were.
* A missing price day is carried forward. Bad prices in the source data are not
  filtered and go straight into the index.
"""


def _button_id(level, name) -> dict:
    return {"type": "mk-group", "level": level, "name": name}


@functools.lru_cache(maxsize=1)
def _groups() -> list[tuple[str, int, list[tuple[str, int]]]]:
    """(sector, ticker count, [(industry, ticker count), ...]) in display order.

    Every ticker counts, delisted ones included: leaving them out would make each
    index the record of the survivors only.
    """
    stocks = data.get_stocks()
    sectors = sorted(stocks[config.SECTOR_COL].unique(), key=lambda s: (s in CATCH_ALL_SECTORS, s))
    groups = []
    for sector in sectors:
        rows = stocks[stocks[config.SECTOR_COL] == sector]
        industries = rows[config.INDUSTRY_COL].value_counts().sort_index()
        # An industry that is its whole sector under the same name would be a
        # second button for the same index.
        if list(industries.index) == [sector]:
            industries = industries.iloc[:0]
        groups.append((sector, len(rows), list(industries.items())))
    return groups


def _tickers(level: str, name: str) -> tuple[str, ...]:
    stocks = data.get_stocks()
    column = config.SECTOR_COL if level == SECTOR else config.INDUSTRY_COL
    return tuple(stocks.loc[stocks[column] == name, "ticker"])


def _group_button(level: str, name: str, count: int) -> html.Button:
    return html.Button(
        [name, html.Span(count, className="group-btn-count")],
        id=_button_id(level, name),
        n_clicks=0,
        className=f"group-btn group-btn--{level}",
    )


def _picker() -> html.Div:
    rows = []
    for sector, count, industries in _groups():
        rows.append(_group_button(SECTOR, sector, count))
        rows.append(
            html.Div(
                [_group_button(INDUSTRY, name, n) for name, n in industries],
                className="group-picker-industries",
            )
        )
    return html.Div(
        [
            html.Div(
                [
                    html.Label("Sector", className="field-label"),
                    html.Label("Industries", className="field-label"),
                ],
                className="group-picker-head",
            ),
            html.Div(rows, className="group-picker-grid"),
            html.Button("Clear selection", id="mk-clear", n_clicks=0, className="group-clear"),
        ],
        className="group-picker",
    )


def layout():
    months = _months()
    marks = {
        i: {"label": str(months[i].year), "style": {"color": theme.MUTED, "fontSize": "11px"}}
        for i in range(0, len(months), 60)
    }
    end = data.get_meta()["price_date_max"]

    return html.Div(
        [
            components.nav_bar("/market"),
            html.Main(
                [
                    html.H1("Market", className="page-title"),
                    html.P(
                        "Sector and industry indexes, bought at the start of the window "
                        "and held. Pick groups below to compare them.",
                        className="page-subtitle",
                    ),
                    dcc.Store(id="mk-selected", data=[]),
                    _picker(),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Weighting", className="field-label"),
                                    dcc.RadioItems(
                                        id="mk-method",
                                        options=[
                                            {"label": "Market cap", "value": group_index.CAP},
                                            {"label": "Equal", "value": group_index.EQUAL},
                                        ],
                                        value=group_index.CAP,
                                        className="checklist",
                                    ),
                                ],
                                className="field field--narrow",
                            ),
                            html.Div(
                                [
                                    html.Label("Period", className="field-label"),
                                    dcc.RangeSlider(
                                        id="mk-slider",
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
                                        id="mk-dates",
                                        min_date_allowed=months[0],
                                        max_date_allowed=end,
                                        start_date=months[0],
                                        end_date=end,
                                        display_format="YYYY-MM-DD",
                                    ),
                                ],
                                className="field field--narrow",
                            ),
                            html.Div(
                                [
                                    html.Label("Scale", className="field-label"),
                                    dcc.RadioItems(
                                        id="mk-scale",
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
                    html.Div(id="mk-summary", className="summary"),
                    dcc.Loading(
                        [
                            dcc.Graph(
                                id="mk-chart",
                                style={"height": "62vh"},
                                config={"displaylogo": False, "scrollZoom": True},
                            ),
                            html.Div(id="mk-tables", className="group-tables"),
                        ],
                        type="default",
                    ),
                    dcc.Markdown(METHOD_NOTES, mathjax=True, className="method-notes"),
                ],
                className="page",
            ),
        ]
    )


# See the note in home.py: registration happens after `layout` exists so it can
# be passed explicitly.
dash.register_page(__name__, path="/market", name="Market", order=2.5, layout=layout)


# --- selection ---------------------------------------------------------------


@callback(
    Output("mk-selected", "data"),
    Input(_button_id(ALL, ALL), "n_clicks"),
    Input("mk-clear", "n_clicks"),
    State("mk-selected", "data"),
    prevent_initial_call=True,
)
def _toggle(_clicks, _clear, selected):
    """Add or remove the clicked group, keeping the order groups were picked in.

    That order decides each line's colour, so a group keeps its colour while
    others are toggled around it.
    """
    trigger = ctx.triggered_id
    if trigger == "mk-clear":
        return []
    # A re-rendered button reports n_clicks 0; only a real click counts.
    if not trigger or not ctx.triggered[0]["value"]:
        return no_update

    key = [trigger["level"], trigger["name"]]
    selected = list(selected or [])
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    return selected


@callback(
    Output(_button_id(ALL, ALL), "style"),
    Input("mk-selected", "data"),
)
def _style_buttons(selected):
    """Selected buttons take their line's colour, so the menu is a legend too."""
    selected = [tuple(key) for key in (selected or [])]
    styles = []
    for output in ctx.outputs_list:
        key = (output["id"]["level"], output["id"]["name"])
        if key not in selected:
            styles.append({})
            continue
        colour = theme.colour_for(selected.index(key)) or theme.MUTED
        styles.append(
            {
                "borderColor": colour,
                "boxShadow": f"inset 0 0 0 1px {colour}",
                "backgroundColor": colour + "1f",
                "color": theme.TEXT_PRIMARY,
                "fontWeight": 600,
            }
        )
    return styles


@callback(
    Output("mk-slider", "value"),
    Output("mk-dates", "start_date"),
    Output("mk-dates", "end_date"),
    Input("mk-slider", "value"),
    Input("mk-dates", "start_date"),
    Input("mk-dates", "end_date"),
    prevent_initial_call=True,
)
def _sync_window(slider_value, start_date, end_date):
    """Keep slider and date pickers on the same window (see relative_performance)."""
    if ctx.triggered_id == "mk-slider":
        low, high = slider_value
        return no_update, _to_date(low, upper=False), _to_date(high, upper=True)
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    return [_to_index(start), _to_index(end)], no_update, no_update


# --- chart and tables --------------------------------------------------------


def _members_table(result: group_index.GroupIndex) -> dash_table.DataTable:
    members = result.members.sort_values("market_cap", ascending=False, na_position="last")
    display = pd.DataFrame(
        {
            "ticker": members["ticker"],
            "market_cap": members["market_cap"].round(0),
            "entry_weight": (members["entry_weight"] * 100).round(2),
            "change": (members["change"] * 100).round(1),
            "joined": members["joined"].dt.strftime("%Y-%m-%d").fillna(""),
            "left": members["left"].dt.strftime("%Y-%m-%d").fillna(""),
        }
    )

    columns = [
        {"name": "Ticker", "id": "ticker"},
        {"name": "Mkt cap $M", "id": "market_cap", "type": "numeric",
         "format": Format(precision=0, scheme=Scheme.fixed, group=Group.yes)},
        {"name": "Weight %", "id": "entry_weight", "type": "numeric",
         "format": Format(precision=2, scheme=Scheme.fixed)},
        {"name": "Change %", "id": "change", "type": "numeric",
         "format": Format(precision=1, scheme=Scheme.fixed, sign=Sign.positive)},
        {"name": "Joined", "id": "joined"},
        {"name": "Left", "id": "left"},
    ]
    return dash_table.DataTable(
        columns=columns,
        data=display.to_dict("records"),
        sort_action="native",
        fixed_rows={"headers": True},
        style_table={"overflowX": "auto", "maxHeight": "320px"},
        style_cell={
            "fontFamily": "var(--font-mono)",
            "fontSize": "12px",
            "padding": "4px 8px",
            "textAlign": "right",
            "minWidth": "70px",
        },
        style_cell_conditional=[
            {"if": {"column_id": "ticker"}, "textAlign": "left"},
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


def _group_card(level: str, name: str, colour: str | None, result: group_index.GroupIndex) -> html.Div:
    level_now = result.level.dropna()
    change = (level_now.iloc[-1] - 1) * 100
    held_now = int(result.n_held.iloc[-1])
    left = int(result.members["left"].notna().sum())
    joined = int(result.members["joined"].notna().sum())

    notes = [f"{change:+.1f}%", f"{held_now} stocks at the end"]
    if joined:
        notes.append(f"{joined} joined")
    if left:
        notes.append(f"{left} left")
    if result.n_left_out:
        notes.append(f"{result.n_left_out} without a market cap left out")

    return html.Div(
        [
            html.Div(
                [
                    html.Span(className="group-swatch", style={"backgroundColor": colour or theme.MUTED}),
                    html.Span(name, className="group-card-title"),
                    html.Span(level, className="group-card-level"),
                ],
                className="group-card-head",
            ),
            html.Div(" · ".join(notes), className="group-card-note"),
            _members_table(result),
        ],
        className="group-card",
    )


@callback(
    Output("mk-chart", "figure"),
    Output("mk-summary", "children"),
    Output("mk-tables", "children"),
    Input("mk-dates", "start_date"),
    Input("mk-dates", "end_date"),
    Input("mk-selected", "data"),
    Input("mk-method", "value"),
    Input("mk-scale", "value"),
)
def _update(start_date, end_date, selected, method, scale):
    if not selected:
        return theme.empty_figure("Pick a sector or an industry above."), "", []

    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    figure = go.Figure()
    cards, skipped = [], []
    low, high = 1.0, 1.0

    for position, (level, name) in enumerate(selected):
        prices, caps = data.get_price_panel(_tickers(level, name))
        result = group_index.build(prices, caps, start, end, method)
        series = result.level.dropna()
        if series.empty:
            reason = "no market caps" if method == group_index.CAP and result.n_left_out else "no prices"
            skipped.append(f"{name} ({reason})")
            continue

        percent = (series - 1) * 100
        held = result.n_held.loc[series.index]
        low, high = min(low, series.min()), max(high, series.max())
        colour = theme.colour_for(position)
        is_context = colour is None

        trace_type = go.Scattergl if len(series) > 40_000 else go.Scatter
        figure.add_trace(
            trace_type(
                x=series.index,
                y=series if scale == "log" else percent,
                # Formatted here rather than by a format spec in the template:
                # Plotly sends numeric arrays to the browser as binary, and the
                # hover then ignores the spec and prints full precision.
                customdata=[[f"{p:+.2f}", f"{n:.0f}"] for p, n in zip(percent, held)],
                name=name,
                mode="lines",
                line=dict(color=colour or theme.MUTED, width=2 if not is_context else 1),
                opacity=theme.CONTEXT_OPACITY if is_context else theme.SERIES_OPACITY,
                showlegend=False,  # the tables below are the legend
                hovertemplate=(
                    f"<b>{name}</b>  %{{customdata[0]}}%"
                    "  · %{customdata[1]} stocks<extra></extra>"
                ),
            )
        )
        cards.append(_group_card(level, name, colour, result))

    if not cards:
        return theme.empty_figure("No data for these groups in this window."), "; ".join(skipped), []

    figure.update_layout(theme.base_layout(yaxis=_y_axis(scale, low, high)))

    parts = [f"{len(cards)} indexes · {METHOD_LABELS[method]} · {start.date()} to {end.date()}"]
    if len(cards) > theme.MAX_COLOURED_SERIES:
        parts.append(
            f"first {theme.MAX_COLOURED_SERIES} coloured, "
            f"{len(cards) - theme.MAX_COLOURED_SERIES} shown as context"
        )
    if skipped:
        parts.append("not shown: " + ", ".join(skipped))
    return figure, " · ".join(parts), cards
