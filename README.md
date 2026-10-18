# ScreenerApp

A Plotly Dash screener over local fundamental and price data.

## Running it

Two commands, both from the project folder in the VSCode terminal:

```
.venv\Scripts\python.exe building_features.py   # only after new data (~1 minute)
.venv\Scripts\python.exe app.py                 # start the app
```

Then open <http://127.0.0.1:8050>. Stop the app with `Ctrl+C`.

## When you drop in new data

Replace the raw files in `data/` and run `building_features.py`. That is the
only step - it builds the feature files and then the app snapshot
(`prepare_data.py`), and the app picks them up the next time it starts.

| File in `data/` | What it is |
|---|---|
| `prices_raw.parquet` | daily prices, EODHD history continued by yfinance |
| `fundamentals_raw.parquet` | quarterly statements from EODHD |
| `tickers.parquet` | one row per ticker: name, sector, industry, exchange |
| `fx_rates.parquet` | units of each currency per 1 USD |
| `index_prices.parquet` | optional - GSPC, for the S&P 500 columns (`gspc_*`) |

`data/` is not tracked by git, so the parquet files stay local.

## What the build does

`building_features.py` turns the raw drop into two files in `data/processed/`:

* `fundamental_features.parquet` - one row per ticker and quarter: the
  statements in millions plus TTM sums, growth, CAGRs, margins, leverage and
  returns on capital.
* `price_features.parquet` - one row per ticker and trading day: the
  total-return `close`, forward price changes, market cap, dividend yield and
  every price-to-fundamentals ratio (P/E, P/S, EV/EBITDA, PEG, ...).

Each price day gets the newest quarter that had been **published** by then (the
earnings release, or the filing when that came first), never one still being
prepared.

### Stale fundamentals

Fundamentals stop at the EODHD download day (`fund_snapshot`); prices carry on
from yfinance. Once a company has published a newer quarter than the data
holds, a P/E built from the old one is wrong. So after the download day the
build predicts each company's next report - the earlier of "the same quarter's
report last year + 52 weeks" and "next quarter end + its shortest recent
reporting lag", which lands before the real report 99 % of the time - and from
three days before it marks the price days `fund_stale` and blanks the ratios.
The same happens whenever a quarter is missing from the data for over two
months. Market cap stays: a share count drifts slowly.

The screener therefore shows two dates: `fundamental date` (the quarter behind
the fundamentals) and `valuation date` (the last day the ratios were valid,
which is where its P/E and friends come from).

## Why there is a build step

The price feature file is ~0.7 GB. Loading it on every start would cost minutes
and more memory than the machine has spare. Instead:

* `prepare_data.py` precomputes the one thing the screener needs all at once -
  the newest row per ticker with fundamentals and sector joined - into a
  ~0.8 MB file, plus a small `stocks.parquet`, the US session calendar and a
  `meta.json` manifest.
* Long history is **not** copied. The feature files are sorted by ticker with
  whole tickers per row group, so parquet skips the groups it does not need;
  one ticker's history costs a few hundredths of a second and is cached after
  the first read. That is what lets a page chart any of the 200+ indicators
  without a 0.7 GB load.

## Layout

```
app.py                      entry point; imports the pages
building_features.py        the build step: raw drop -> feature files (then prepare_data)
prepare_data.py             feature files -> the app's start-up snapshot
screenerapp/
  config.py                 paths, constants, defaults
  data.py                   loading and caching
  indicators.py             the indicator catalog
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
US session - the date pickers allow any calendar day.

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
does (`EnterpriseValue = MarketCap + netDebt`):

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

## Notes on the data

* **Universe.** Every S&P 500 member EODHD knows (current and former) plus
  Nasdaq-100 and Dow members, and ~120 large non-US companies (US-listed ADRs
  and home listings, the latter priced in their own currency). The non-US ones
  have prices only - no fundamentals, sector or name yet - so they appear under
  "Unclassified" and are left out of the heatmap, which needs a market cap.
  ETFs are not in the price file.
* **Share counts** are on the newest split basis, so they line up with the
  latest `close` (BKNG's 25-for-1 split of April 2026 included). Market cap is
  the traded price times the share count of the day.
* **Reused symbols** (ADT, DELL, SE, ... and the tail of MON, XL, NVLS, HSH)
  are dropped or cut where the series switches company - see the lists at the
  top of `building_features.py`.
* **Units.** Money columns are in millions; `MarketCap` and `EnterpriseValue`
  are in USD for every ticker. Margins, changes, yields and CAGRs are fractions
  in the data (0.4667) and rendered as percentages (46.67%). A price ratio of
  -1 means the denominator is negative (a loss-maker's P/E).
* **Forward changes.** `close_chg_1y` etc. look *forward* from the date (they
  are blank for the last N years), matching the old feature files.
