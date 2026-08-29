# ScreenerApp

A Plotly Dash screener over local fundamental and price data.

## Running it

Two commands, both from the project folder in the VSCode terminal:

```
.venv\Scripts\python.exe prepare_data.py     # only after new data
.venv\Scripts\python.exe app.py              # start the app
```

Then open <http://127.0.0.1:8050>. Stop the app with `Ctrl+C`.

## When you drop in new data

Replace the files in `data/` and run `prepare_data.py` again. That is the only
step - the app picks up the rebuilt files the next time it starts.

`data/` is not tracked by git, so the parquet files stay local.

## Why there is a build step

`pe_model_price_features.parquet` is 1.2 GB. Loading it on every start would
cost minutes and more memory than the machine has spare. Instead:

* `prepare_data.py` precomputes the one thing the screener needs all at once -
  the newest row per ticker with fundamentals and sector joined - into an 883 KB
  file, plus a small `stocks.parquet` and a `meta.json` manifest.
* Long history is **not** copied. The raw price file is already sorted by
  ticker, so parquet skips the row groups it does not need; one ticker's history
  costs about 0.03s and is cached after the first read. That is what lets a page
  chart any of the 190 indicators without a 1.2 GB load.

## Layout

```
app.py                      entry point; imports the pages
prepare_data.py             the build step
screenerapp/
  config.py                 paths, constants, defaults
  data.py                   loading and caching
  indicators.py             the indicator catalog (190 columns)
  theme.py                  chart palette and Plotly styling
  components.py             nav bar + the shared filter panel
  pages/
    home.py                     landing page
    screener.py                 the table
    relative_performance.py     the rebased line chart
    heatmap.py                  sector treemap of price change
    indicator_distribution.py   market histograms / density map
    inspection.py               indicators through time, two y-axes
    dcf.py                      cash-flow valuation, forward and reverse
assets/style.css            app styling
data/                       raw drops (gitignored) + processed/
```

## Two ways data is read

Which one a page needs decides how it should ask:

* **Few tickers, all dates** (relative performance) - `data.get_history(tickers,
  columns)`. Cached per ticker, so adding one stock costs one read.
* **All tickers, one date** (heatmap, indicator distribution) -
  `data.get_cross_section(date, columns)`, or `data.get_price_change(start, end)`
  for a two-date change. The file is sorted by ticker, so a date filter cannot
  prune row groups; reading a few columns still lands in a few tenths of a
  second and every answer is cached.

`data.snap_to_trading_date(d)` moves a weekend or holiday back to the previous
session - the date pickers allow any calendar day.

## Adding a page

1. Create `screenerapp/pages/your_page.py`.
2. Call `dash.register_page(__name__, path="/your-path", name="Your Page", order=N)`.
3. Use `components.nav_bar(...)` and `components.filter_panel("your-page")` to
   get the navigation and the sector/industry/stock filters - the cascade
   callbacks are pattern-matching and pick up the new page automatically.
4. Add it to the import list in `app.py`.

`data.get_history(tickers, columns)` gives long-format history for any indicator,
and `data.get_catalog()` describes every available column.

## The DCF model

Free-cash-flow based, in millions, bridging to equity the same way the data
does (`EnterpriseValue = MarketCap + netDebt`, which holds exactly in the file):

1. Grow TTM free cash flow at your rate for N years, discounting each year.
2. Add a terminal value, `FCF_N x (1 + terminal) / (discount - terminal)`,
   discounted back.
3. Subtract net debt, divide by shares outstanding.

The reverse direction fixes the price and solves for the growth rate by
bisection - value rises monotonically with growth, so it converges without a
solver dependency. The growth box is seeded from the company's own
`TTM_freeCashFlow_CAGR_20q`, clamped to -20%..35%.

It refuses rather than guesses when the inputs cannot mean anything: negative
free cash flow, a terminal rate at or above the discount rate, or a price
outside the range the model can produce.

## Notes on the current data drop

* **Uneven end dates.** ~94 tickers stop at 2026-01-30 while the rest run to
  2026-02-13, and they are mostly alphabetically late (SO, T, SYK, SPGI). These
  are still-trading names, so this looks like the price extraction being cut
  short rather than 94 delistings. `config.ACTIVE_WINDOW_DAYS` is set to 30 so
  they still count as active; tighten it once a drop lands with an even end date.
* **Ticker coverage.** 753 tickers have prices; 781 have fundamentals. The app
  uses the 753 with prices, since every page needs a price.
* **Units.** Money columns are in millions. Margins, changes and CAGRs are
  fractions in the data (0.4667) and rendered as percentages (46.67%).
