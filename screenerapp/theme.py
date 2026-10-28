"""Chart palette and Plotly styling.

The first eight categorical hues and the chrome colors below are the reference
data-viz palette, used unchanged and in its documented slot order - that
ordering is what keeps adjacent series distinguishable under colour-vision
deficiency, so reordering the list is not a cosmetic change.

Slots 9-12 extend it for portfolios of up to twelve stocks. They were searched
with the reference validator's checks (OKLCH lightness band and chroma floor,
3:1 contrast on the surface, OKLab Delta E): each sits at least 15 from every
other slot under normal vision, and adjacent slots stay at least 8 apart under
simulated protan/deutan vision. Past about twelve, no further hue clears those
floors - the next candidates repeat a pink or a blue.

Charts never cycle the palette: series past the twelfth are drawn in a muted
neutral as context rather than given a hue that would match an existing slot.
"""

from __future__ import annotations

import plotly.graph_objects as go

# Categorical slots, in validated order.
SERIES = (
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
    "#a50371",  # wine
    "#977d30",  # olive
    "#b235ec",  # purple
    "#7c4111",  # brown
)
MAX_COLOURED_SERIES = len(SERIES)

# Loss-to-gain scale for the heatmap. These are the reserved status colours
# rather than categorical slots, which is right here: the hue genuinely means
# good/bad, not identity. The midpoint is neutral grey so "no change" reads as
# nothing, and lightness varies along both arms so the scale still carries some
# signal in greyscale or under red-green colour blindness - though red/green is
# the weakest pairing for that, and a red-to-blue variant is a one-line swap.
DIVERGING_LOSS_GAIN = (
    (0.00, "#7d1a1a"),
    (0.25, "#d03b3b"),
    (0.50, "#f0efec"),
    (0.75, "#0ca30c"),
    (1.00, "#0a5c0a"),
)

# One-sided variants of the same two arms, for measures that can only fall on
# one side of zero: distance below a period high is never positive, distance
# above a period low is never negative. A diverging scale there would spend half
# its range on values that cannot occur.
SEQUENTIAL_LOSS = (  # cmin = -bound (dark red) .. cmax = 0 (neutral)
    (0.00, "#7d1a1a"),
    (0.50, "#d03b3b"),
    (1.00, "#f0efec"),
)
SEQUENTIAL_GAIN = (  # cmin = 0 (neutral) .. cmax = +bound (dark green)
    (0.00, "#f0efec"),
    (0.50, "#0ca30c"),
    (1.00, "#0a5c0a"),
)

# One hue, light to dark - for density/magnitude, never for identity.
SEQUENTIAL_BLUE = (
    (0.00, "#fcfcfb"),
    (0.20, "#cde2fb"),
    (0.40, "#9ec5f4"),
    (0.60, "#5598e7"),
    (0.80, "#2a78d6"),
    (1.00, "#184f95"),
)

SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"

FONT_STACK = 'system-ui, -apple-system, "Segoe UI", sans-serif'
FONT_MONO = 'ui-monospace, "Cascadia Mono", "Consolas", monospace'

# Opacity for the coloured series and for the unnamed context series behind them.
SERIES_OPACITY = 0.75
CONTEXT_OPACITY = 0.30


def colour_for(position: int) -> str | None:
    """Hue for the nth series, or None once the palette is exhausted."""
    return SERIES[position] if position < MAX_COLOURED_SERIES else None


def base_layout(**overrides) -> go.Layout:
    """Recessive chrome: hairline grid, no chart junk, generous margins."""
    layout = dict(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT_STACK, size=12, color=TEXT_SECONDARY),
        margin=dict(l=60, r=24, t=16, b=48),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=SURFACE,
            bordercolor=BASELINE,
            font=dict(family=FONT_STACK, size=12, color=TEXT_PRIMARY),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            font=dict(size=11, color=TEXT_SECONDARY),
            bgcolor="rgba(0,0,0,0)",
        ),
        xaxis=dict(
            showgrid=True,
            gridcolor=GRIDLINE,
            gridwidth=1,
            linecolor=BASELINE,
            zeroline=False,
            tickfont=dict(color=MUTED),
            hoverformat="%Y-%m-%d",
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikecolor=BASELINE,
            spikethickness=1,
            spikedash="solid",
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=GRIDLINE,
            gridwidth=1,
            linecolor=BASELINE,
            zeroline=True,
            zerolinecolor=BASELINE,
            zerolinewidth=1,
            tickfont=dict(color=MUTED),
        ),
    )
    layout.update(overrides)
    return go.Layout(**layout)


def empty_figure(message: str) -> go.Figure:
    """Placeholder that keeps the chart's footprint while it has nothing to show."""
    figure = go.Figure(layout=base_layout(hovermode=False))
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    figure.add_annotation(
        text=message,
        showarrow=False,
        font=dict(family=FONT_STACK, size=13, color=MUTED),
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
    )
    return figure
