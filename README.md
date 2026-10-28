# ScreenerApp

A Plotly Dash screener over the user's own fundamental and price data.

## Running it

From the project folder in the VSCode terminal:

```
.venv\Scripts\python.exe app.py
```

Then open <http://127.0.0.1:8050>. Stop the app with `Ctrl+C`.

## Where the data comes from

All data comes from the `features` package (`C:\Users\barto\VSCodeProjects\1_FeaturesBuilder`),
installed editable into this venv:

```
.venv\Scripts\python.exe -m pip install -e C:/Users/barto/VSCodeProjects/1_FeaturesBuilder/packages/features
```

It finds its own build (`1_FeaturesBuilder/data/features/v1`). New data means a new
`features build` in that project; then restart the app. Column definitions, units and
missing-value rules are in `1_FeaturesBuilder/docs/features.md`, and in the app on the
**Features** page (`/features`): every column with its formula, inputs, dependents and
whether the app offers it, searchable and sortable. A feature that is wrong or missing is
changed in the package, not here.

### Updating the data

`update_data.py` runs the whole chain, each step in its own project and venv, and stops
at the first failure:

```
.venv\Scripts\python.exe update_data.py                  # free prices (yfinance, FRED) + rebuild all
.venv\Scripts\python.exe update_data.py --eodhd          # paid EODHD download first (subscription month)
.venv\Scripts\python.exe update_data.py --no-download    # rebuild from the files on disk
.venv\Scripts\python.exe update_data.py --dry-run        # print the steps only
```

Download -> `0_EODHD_download/data/3_output` -> copied to `1_FeaturesBuilder/input_data`
-> `features build` -> the app cache below. Restart the app afterwards.

What this project builds on top of the package is page-specific:

* **The start-up cache** (`screenerapp/cache.py` -> `data/cache/`, ~5 s). `app.py`
  rebuilds it by itself when the features build has changed (its `build_id`):
  * `snapshot.parquet` - one row per ticker for the screener and the DCF;
  * `trading_dates.parquet` - the US session calendar the date pickers snap to.
* **Reads on demand** in `screenerapp/data.py`: one ticker's history (a few hundredths
  of a second), every ticker on one date (about a tenth), the heatmap's price window.
  Each answer is cached for the life of the process.
* **The indicator catalog** (`screenerapp/indicators.py`): which package columns the
  dropdowns offer, grouped and formatted by the package's own units and categories.

## The app's rules on top of the features

* **Ratios.** Price columns come through the package's screener view: P/E, P/FCF,
  EV/EBITDA, ... are blank for a negative or zero denominator (no -1 placeholder; the
  signed values are `pe_signed`, `PFCF_signed`, ... in the package), and leverage and
  returns on capital (ROE, ROA, ROIC, ...) are blank for a denominator up to 1 M, also
  on quarterly rows.
* **Stale fundamentals.** Fundamentals stop at the download day while prices carry on.
  Once the next report is due and not in the data, the price-to-fundamental ratios go
  blank (`fund_stale`). The screener therefore shows two dates: `fundamental date` (the
  quarter behind the fundamentals) and `valuation date` (the last day the ratios were
  valid, which is where its P/E and friends come from).
* **Currency.** Fundamentals are in each ticker's trading currency; MarketCap and
  EnterpriseValue are USD. Pages that rank tickers against each other (screener,
  distribution) convert amounts to USD; the DCF and the inspection charts stay in the
  stock's own currency.
* **Active tickers.** A ticker is active when its last price is within 30 days of the
  newest price; inactive ones are hidden behind a toggle.
* **Hidden columns.** Forward-looking columns (`close_chg_1y`, ...) use the future, so
  no page offers them; nor the `*_signed` and `*_local` duplicates.

## Layout

```
app.py                      entry point; checks the cache, imports the pages
screenerapp/
  config.py                 cache paths, constants, defaults
  cache.py                  the start-up cache: snapshot + trading calendar
  data.py                   reading from the package, and caching
  indicators.py             the indicator catalog
  theme.py                  chart palette and Plotly styling
  components.py             nav bar + the shared filter panel
  feature_docs.py           the feature documentation table, from the package registry
  group_index.py            buy-and-hold sector/industry indexes (market page)
  pages/
    home.py                     landing page
    screener.py                 the table
    relative_performance.py     the rebased line chart
    market.py                   sector and industry indexes, with their member tables
    heatmap.py                  sector treemap of price change
    indicator_distribution.py   market histograms / density map
    inspection.py               indicators through time, two y-axes
    dcf.py                      cash-flow valuation, forward and reverse
    features_docs.py            documentation of every feature (feature_docs.py builds it)
    configuration.py            the portfolio, saved in the browser; the Portfolio button reads it
assets/style.css            app styling
data/cache/                 the start-up cache (gitignored)
```

## Two ways data is read

Which one a page needs decides how it should ask:

* **Few tickers, all dates** (relative performance, inspection) -
  `data.get_history(tickers, columns, source)`. Price columns give one row per trading
  day, fundamental columns one per quarter. Cached per ticker.
* **All tickers, one date** (heatmap, indicator distribution) -
  `data.get_cross_section(date, columns)`, or `data.get_price_change(start, end)` for a
  two-date change. A fundamental column is the quarter in force that day, by the
  package's point-in-time rule.
* **A group's tickers, all dates, wide** (market) - `data.get_price_panel(tickers)`:
  USD total-return close and market cap, date x ticker, carried forward inside each
  ticker's life. Cached per group.

`data.snap_to_trading_date(d)` moves a weekend or holiday back to the previous US
session - the date pickers allow any calendar day.

## Adding a page

1. Create `screenerapp/pages/your_page.py`.
2. Call `dash.register_page(__name__, path="/your-path", name="Your Page", order=N)`.
3. Use `components.nav_bar(...)` and `components.filter_panel("your-page")` to get the
   navigation and the sector/industry/stock filters - the cascade callbacks are
   pattern-matching and pick up the new page automatically.
4. Add it to the import list in `app.py`.

`data.get_catalog()` describes every column a page can offer.

## The DCF model

Free-cash-flow based, in millions of the stock's trading currency, bridging to equity
the same way the data does (`EnterpriseValue = MarketCap + netDebt`):

1. Grow TTM free cash flow at your rate for N years, discounting each year.
2. Add a terminal value, `FCF_N x (1 + terminal) / (discount - terminal)`, discounted
   back.
3. Subtract net debt, divide by the share count MarketCap uses
   (`commonStockSharesOutstanding_carried`), compare with the traded price
   (`price_split_adj`).

The reverse direction fixes the price and solves for the growth rate by bisection -
value rises monotonically with growth, so it converges without a solver dependency.
The growth box is seeded from the company's own `TTM_freeCashFlow_CAGR_20q`, clamped
to -20%..35%.

It refuses rather than guesses when the inputs cannot mean anything: negative free
cash flow, a terminal rate at or above the discount rate, or a price outside the range
the model can produce.
