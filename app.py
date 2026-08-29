"""ScreenerApp entry point.

    .venv\\Scripts\\python.exe app.py

Then open http://127.0.0.1:8050 in a browser.

Pages are imported explicitly below rather than auto-discovered, so that they
stay inside the ``screenerapp`` package and can share code through normal
imports. To add a page: create a module in screenerapp/pages/, call
``dash.register_page`` in it, and add it to the import list here.
"""

from __future__ import annotations

import sys

from dash import Dash, html, page_container

from screenerapp import data

app = Dash(
    __name__,
    use_pages=True,
    pages_folder="",
    title="ScreenerApp",
    update_title=None,
    suppress_callback_exceptions=True,
)
server = app.server

# pages_folder="" disables Dash's file-system discovery, so importing the
# modules is what registers them. This has to happen after the app exists -
# register_page() looks the app up on the way in.
from screenerapp.pages import (  # noqa: E402,F401
    dcf,
    heatmap,
    home,
    indicator_distribution,
    inspection,
    relative_performance,
    screener,
)

app.layout = html.Div([page_container], className="app-root")


def preflight() -> None:
    """Fail with instructions rather than a stack trace if the build step is due."""
    try:
        meta = data.get_meta()
    except data.DataNotPreparedError as exc:
        sys.exit(f"\n{exc}\n")

    print(
        f"Data built {meta['built_at']} · "
        f"{meta['n_active']:,} active of {meta['n_tickers']:,} tickers · "
        f"prices through {meta['price_date_max']}"
    )


if __name__ == "__main__":
    preflight()
    app.run(debug=True)
