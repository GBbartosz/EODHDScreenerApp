"""DCF - discounted cash flow, forwards and in reverse.

Forward: choose how cash flow grows and see what the stock is worth.
Reverse: take the market price as given and solve for the growth rate that
would justify it. The reverse direction is usually the more honest question,
because it replaces a guess with "here is what you would have to believe".

Growth runs in two stages. The first few years take an explicit rate each -
that is where a view actually lives, and where a straight-line rate is least
defensible. The remaining years share one constant rate, then a terminal value
closes it out.

The starting cash flow is an input rather than simply the last reported figure.
A quarter distorted by a one-off - a legal settlement, a tax charge, a big
working-capital swing - would otherwise propagate through every forecast year
and the terminal value with it.

The model bridges to equity the way the data does: the file's own
EnterpriseValue equals MarketCap + netDebt exactly, so subtracting net debt
from enterprise value is the consistent step. Everything from the data is in
millions; per-share figures are in dollars.
"""

from __future__ import annotations

import dash
import pandas as pd
from dash import ALL, Input, Output, State, callback, dash_table, dcc, html

from .. import components, data, theme

PAGE = "dcf"

# Rows of the context table, in reading order: scale, then margins, then the
# cash flow the model runs on, then the balance-sheet bridge.
CONTEXT_FEATURES = (
    "totalRevenue",
    "TTM_totalRevenue",
    "TTM_totalRevenue_chg_4q",
    "TTM_totalRevenue_CAGR_20q",
    "grossMargin",
    "operatingMargin",
    "netMargin",
    "FCFMargin",
    "ebitda",
    "ebit",
    "netIncome",
    "TTM_netIncome",
    "totalCashFromOperatingActivities",
    "capitalExpenditures",
    "freeCashFlow",
    "TTM_freeCashFlow",
    "TTM_freeCashFlow_chg_4q",
    "TTM_freeCashFlow_CAGR_20q",
    "commonStockSharesOutstanding",
    "totalDebt",
    "cashAndShortTermInvestments",
    "netDebt",
)

QUARTERS = 20  # five years

MAX_EXPLICIT_YEARS = 10
DEFAULT_EXPLICIT_YEARS = 2
DEFAULT_TAIL_YEARS = 8
DEFAULT_TERMINAL_PCT = 2.5
DEFAULT_DISCOUNT_PCT = 10.0
DEFAULT_GROWTH_PCT = 5.0

STAGE_INPUT = "dcf-stage-growth"


# --- the model -------------------------------------------------------------


def equity_per_share(
    base_fcf: float,
    stage_growths: list[float],
    tail_years: int,
    tail_growth: float,
    terminal: float,
    discount: float,
    net_debt: float,
    shares: float,
) -> float | None:
    """Present value of the forecast plus its terminal value, less net debt.

    Rates are fractions (0.05 for 5%). Returns None when the inputs cannot
    produce a finite value - a terminal rate at or above the discount rate
    implies a company that eventually outgrows the whole economy.
    """
    if shares <= 0 or discount <= terminal:
        return None

    present_value = 0.0
    cash = base_fcf
    year = 0

    for growth in stage_growths:
        year += 1
        cash *= 1 + growth
        present_value += cash / (1 + discount) ** year

    for _ in range(int(tail_years)):
        year += 1
        cash *= 1 + tail_growth
        present_value += cash / (1 + discount) ** year

    terminal_value = cash * (1 + terminal) / (discount - terminal)
    present_value += terminal_value / (1 + discount) ** year

    return (present_value - net_debt) / shares


def implied_growth(
    price: float,
    base_fcf: float,
    total_years: int,
    terminal: float,
    discount: float,
    net_debt: float,
    shares: float,
) -> float | None:
    """The single flat growth rate that makes the model agree with the price.

    Deliberately ignores the per-year stage inputs: the point of the reverse
    question is a number that does not depend on the assumptions being tested.
    Value rises monotonically with growth, so a bisection converges without
    needing a solver dependency.
    """
    if base_fcf <= 0 or shares <= 0 or discount <= terminal:
        return None

    def gap(rate: float) -> float | None:
        value = equity_per_share(
            base_fcf, [], total_years, rate, terminal, discount, net_debt, shares
        )
        return None if value is None else value - price

    low, high = -0.90, 2.00
    low_gap, high_gap = gap(low), gap(high)
    if low_gap is None or high_gap is None or low_gap > 0 or high_gap < 0:
        return None  # the price sits outside anything this model can produce

    for _ in range(200):
        middle = (low + high) / 2
        if gap(middle) < 0:
            low = middle
        else:
            high = middle
    return (low + high) / 2


# --- presentation ----------------------------------------------------------


def _format_value(column: str, value) -> str:
    if pd.isna(value):
        return "—"
    indicator = data.get_catalog().get(column)
    style = indicator.fmt if indicator else "ratio"
    if style in ("money", "int"):
        return f"{value:,.0f}"
    if style == "percent":
        return f"{value * 100:+.1f}%"
    return f"{value:,.2f}"


def _stat(label: str, value: str, note: str = "", tone: str = "") -> html.Div:
    return html.Div(
        [
            html.Div(label, className="stat-label"),
            html.Div(value, className=f"stat-value {tone}".strip()),
            html.Div(note, className="stat-note"),
        ],
        className="stat",
    )


def _number_field(label: str, field_id, value, step: float, **input_kwargs) -> html.Div:
    return html.Div(
        [
            html.Label(label, className="field-label"),
            dcc.Input(
                id=field_id,
                type="number",
                value=value,
                step=step,
                debounce=True,
                className="number-input",
                **input_kwargs,
            ),
        ],
        className="field field--narrow",
    )


def _seed_values(ticker) -> tuple[float | None, float, float | None]:
    """Starting cash flow, growth rate and price to open with, from the stock."""
    if not ticker:
        return None, DEFAULT_GROWTH_PCT, None

    frame = data.get_screener()
    row = frame[frame["ticker"] == ticker]
    if row.empty:
        return None, DEFAULT_GROWTH_PCT, None
    row = row.iloc[0]

    base = row["TTM_freeCashFlow"]
    base = None if pd.isna(base) else round(float(base), 1)

    price = row["close"]
    price = None if pd.isna(price) else round(float(price), 2)

    cagr = row["TTM_freeCashFlow_CAGR_20q"]
    if pd.isna(cagr):
        growth = DEFAULT_GROWTH_PCT
    else:
        # Keep the seed inside a range a forecast can defend.
        growth = round(float(min(max(cagr, -0.20), 0.35)) * 100, 1)
    return base, growth, price


def layout():
    stocks = data.get_stocks()
    options = [
        {"label": f"{row.ticker} · {row.Sector}", "value": row.ticker}
        for row in stocks.itertuples()
    ]

    return html.Div(
        [
            components.nav_bar("/dcf"),
            html.Main(
                [
                    html.H1("DCF", className="page-title"),
                    html.P(
                        "Value a stock from its free cash flow, then ask what growth "
                        "the current price already assumes.",
                        className="page-subtitle",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Stock", className="field-label"),
                                    dcc.Dropdown(
                                        id="dcf-stock",
                                        options=options,
                                        value="AAPL",
                                        multi=False,
                                        placeholder="Pick one stock",
                                    ),
                                ],
                                className="field",
                            ),
                            _number_field("Starting FCF · M", "dcf-base-fcf", None, 100),
                            _number_field("Stock price", "dcf-price", None, 1),
                            _number_field(
                                "Discount rate · %",
                                "dcf-discount",
                                DEFAULT_DISCOUNT_PCT,
                                0.5,
                            ),
                            _number_field(
                                "Terminal growth · %",
                                "dcf-terminal",
                                DEFAULT_TERMINAL_PCT,
                                0.25,
                            ),
                        ],
                        className="filter-panel",
                    ),
                    html.Div(
                        [
                            _number_field(
                                "Explicit years",
                                "dcf-explicit-years",
                                DEFAULT_EXPLICIT_YEARS,
                                1,
                                min=0,
                                max=MAX_EXPLICIT_YEARS,
                            ),
                            html.Div(
                                id="dcf-stage-inputs", className="stage-inputs"
                            ),
                        ],
                        className="filter-panel filter-panel--nested",
                    ),
                    html.Div(
                        [
                            _number_field(
                                "Remaining years",
                                "dcf-tail-years",
                                DEFAULT_TAIL_YEARS,
                                1,
                                min=0,
                                max=50,
                            ),
                            _number_field(
                                "Growth for remaining · %",
                                "dcf-tail-growth",
                                DEFAULT_GROWTH_PCT,
                                0.5,
                            ),
                        ],
                        className="filter-panel filter-panel--nested",
                    ),
                    html.Div(id="dcf-results", className="stat-grid"),
                    html.Div(id="dcf-basis", className="summary"),
                    html.H2("Fundamentals · last 5 years", className="section-title"),
                    dcc.Loading(html.Div(id="dcf-table-wrap"), type="default"),
                ],
                # 20 quarters plus a label column need more room than the
                # reading-width column the other pages use.
                className="page page--wide",
            ),
        ]
    )


dash.register_page(__name__, path="/dcf", name="DCF", order=6, layout=layout)


@callback(
    Output("dcf-base-fcf", "value"),
    Output("dcf-tail-growth", "value"),
    Output("dcf-price", "value"),
    Input("dcf-stock", "value"),
)
def _seed_from_stock(ticker):
    """Open on the company's own TTM cash flow, growth and last close."""
    return _seed_values(ticker)


@callback(
    Output("dcf-stage-inputs", "children"),
    Input("dcf-explicit-years", "value"),
    Input("dcf-stock", "value"),
    State({"type": STAGE_INPUT, "index": ALL}, "value"),
)
def _build_stage_inputs(count, ticker, existing):
    """One growth box per explicit year, keeping whatever is already typed."""
    count = max(0, min(int(count or 0), MAX_EXPLICIT_YEARS))
    if count == 0:
        return html.Div(
            "No explicit years - the whole forecast uses the constant rate below.",
            className="stage-empty",
        )

    _, seed, _ = _seed_values(ticker)
    existing = existing or []

    return [
        _number_field(
            f"Year {index + 1} · %",
            {"type": STAGE_INPUT, "index": index},
            existing[index] if index < len(existing) and existing[index] is not None else seed,
            0.5,
        )
        for index in range(count)
    ]


@callback(
    Output("dcf-results", "children"),
    Output("dcf-basis", "children"),
    Input("dcf-stock", "value"),
    Input("dcf-base-fcf", "value"),
    Input("dcf-price", "value"),
    Input("dcf-discount", "value"),
    Input("dcf-terminal", "value"),
    Input({"type": STAGE_INPUT, "index": ALL}, "value"),
    Input("dcf-tail-years", "value"),
    Input("dcf-tail-growth", "value"),
)
def _update_results(
    ticker,
    base_fcf,
    price,
    discount_pct,
    terminal_pct,
    stage_pcts,
    tail_years,
    tail_growth_pct,
):
    if not ticker:
        return [], "Pick a stock."

    frame = data.get_screener()
    row = frame[frame["ticker"] == ticker]
    if row.empty:
        return [], "No data for this stock."
    row = row.iloc[0]

    reported = row["TTM_freeCashFlow"]
    shares = row["commonStockSharesOutstanding"]
    net_debt = 0.0 if pd.isna(row["netDebt"]) else float(row["netDebt"])
    last_close = None if pd.isna(row["close"]) else float(row["close"])

    if pd.isna(shares) or shares <= 0:
        return [], f"{ticker} has no share count, so a per-share value is not possible."

    if base_fcf is None:
        base_fcf = None if pd.isna(reported) else float(reported)
    if base_fcf is None:
        return [], f"{ticker} has no reported free cash flow - type a starting value."

    # The typed price drives both directions: it is the number the valuation is
    # measured against, so the reverse solve and the upside must agree on it.
    price = float(price) if price is not None else last_close
    if price is None or price <= 0:
        return [], f"{ticker} has no usable price - type one to compare against."

    base_fcf = float(base_fcf)
    discount = float(discount_pct if discount_pct is not None else DEFAULT_DISCOUNT_PCT) / 100
    terminal = float(terminal_pct if terminal_pct is not None else DEFAULT_TERMINAL_PCT) / 100
    tail_years = int(tail_years or 0)
    tail_growth = float(tail_growth_pct if tail_growth_pct is not None else DEFAULT_GROWTH_PCT) / 100
    stage_growths = [
        float(p if p is not None else 0) / 100 for p in (stage_pcts or [])
    ]
    total_years = len(stage_growths) + tail_years

    reported_note = (
        "" if pd.isna(reported) else f" (reported TTM {float(reported):,.0f} M)"
    )
    # Flag an overridden price the same way as an overridden cash flow, so a
    # hypothetical never passes for the market's own number.
    if last_close is not None and abs(price - last_close) > 0.005:
        price_note = f" (last close {last_close:,.2f} on {row['date'].date()})"
    else:
        price_note = f" as of {row['date'].date()}"
    basis = (
        f"Starting FCF {base_fcf:,.0f} M{reported_note} · net debt {net_debt:,.0f} M · "
        f"{shares:,.0f} M shares · price {price:,.2f}{price_note}"
    )

    if discount <= terminal:
        return [], basis + " · discount rate must exceed terminal growth."
    if total_years == 0:
        return [], basis + " · give the forecast at least one year."

    if base_fcf <= 0:
        return (
            [
                _stat("Intrinsic value", "n/a", "starting cash flow is not positive"),
                _stat("Market price", f"{price:,.2f}", ""),
            ],
            basis + " · a DCF on negative cash flow would not mean anything.",
        )

    value = equity_per_share(
        base_fcf, stage_growths, tail_years, tail_growth, terminal, discount, net_debt, shares
    )
    reverse = implied_growth(
        price, base_fcf, total_years, terminal, discount, net_debt, shares
    )

    tiles = []
    if value is None:
        tiles.append(_stat("Intrinsic value", "n/a", "inputs out of range"))
    else:
        upside = value / price - 1 if price else None
        tone = "stat-value--good" if upside and upside > 0 else "stat-value--bad"
        tiles.append(
            _stat(
                "Intrinsic value / share",
                f"{value:,.2f}",
                f"{upside:+.1%} vs market" if upside is not None else "",
                tone,
            )
        )

    if last_close is not None and abs(price - last_close) > 0.005:
        price_label, price_detail = "Price used", f"entered · last close {last_close:,.2f}"
    else:
        price_label, price_detail = "Market price", f"as of {row['date'].date()}"
    tiles.append(_stat(price_label, f"{price:,.2f}", price_detail))

    if reverse is None:
        tiles.append(_stat("Implied growth", "n/a", "price outside the model's range"))
    else:
        tiles.append(
            _stat(
                "Implied FCF growth",
                f"{reverse:+.1%}",
                f"flat for {total_years}y to justify today's price",
            )
        )

    if stage_growths:
        stage_text = " → ".join(f"{g:+.1%}" for g in stage_growths)
        note = f"then {tail_growth:+.1%} for {tail_years}y"
    else:
        stage_text = f"{tail_growth:+.1%}"
        note = f"flat for {tail_years}y"
    tiles.append(_stat("Your assumption", stage_text, note))

    return tiles, basis


@callback(
    Output("dcf-table-wrap", "children"),
    Input("dcf-stock", "value"),
)
def _update_table(ticker):
    if not ticker:
        return html.Div()

    history = data.get_history([ticker], CONTEXT_FEATURES, source="fundamental")
    if history.empty:
        return html.Div("No fundamental history for this stock.", className="summary")

    recent = history.sort_values("date").tail(QUARTERS)
    dates = [d.strftime("%Y-%m-%d") for d in recent["date"]]

    rows = []
    for feature in CONTEXT_FEATURES:
        record = {"feature": feature}
        for date_label, (_, quarter) in zip(dates, recent.iterrows()):
            record[date_label] = _format_value(feature, quarter[feature])
        rows.append(record)

    columns = [{"name": "", "id": "feature"}] + [{"name": d, "id": d} for d in dates]

    return dash_table.DataTable(
        columns=columns,
        data=rows,
        # No fixed_columns here: it splits the table into two stacked layers and
        # collapses the scrollable half to a few columns. A plain overflow-x
        # table fills the page and scrolls normally when the window is narrow.
        style_table={"overflowX": "auto", "width": "100%"},
        style_cell={
            "fontFamily": theme.FONT_MONO,
            "fontSize": "12px",
            "padding": "5px 8px",
            "textAlign": "right",
            "minWidth": "76px",
            "maxWidth": "110px",
        },
        style_cell_conditional=[
            {
                "if": {"column_id": "feature"},
                "textAlign": "left",
                "minWidth": "220px",
                "maxWidth": "260px",
                "fontWeight": "600",
            }
        ],
        style_header={
            "fontWeight": "600",
            "backgroundColor": "var(--surface-2)",
            "textAlign": "right",
            "whiteSpace": "nowrap",
        },
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "var(--surface-2)"}
        ],
    )
