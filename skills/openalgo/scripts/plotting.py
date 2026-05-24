"""Plotly helpers tuned for Indian-market display.

Conventions:
- `template="plotly_dark"` everywhere unless caller overrides.
- Candlesticks use `xaxis_type="category"` so weekends and exchange
  holidays do not produce visible gaps.
- Save to HTML by default (interactive) but accept a `out=None` toggle
  for show()-only flow inside notebooks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go


_TPL = "plotly_dark"


def _maybe_save(fig: go.Figure, out: str | Path | None) -> go.Figure:
    if out:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(str(out), include_plotlyjs="cdn")
        print(f"[plot] saved {out}")
    return fig


def candlestick_no_gaps(
    df: pd.DataFrame,
    *,
    title: str = "",
    overlays: dict[str, pd.Series] | None = None,
    out: str | Path | None = None,
    height: int = 700,
) -> go.Figure:
    """Plot OHLC candles with weekend / holiday gaps removed.

    `overlays` is a dict {label: series} for moving averages, supertrend,
    Bollinger bands, etc. Each series is plotted as a line in the price pane.
    """
    needed = {"open", "high", "low", "close"}
    if not needed.issubset(df.columns):
        raise ValueError(f"df must have OHLC columns; have {list(df.columns)}")

    x_labels = [pd.Timestamp(t).strftime("%Y-%m-%d %H:%M") for t in df.index]
    fig = go.Figure(go.Candlestick(
        x=x_labels,
        open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        name="OHLC",
    ))
    for label, series in (overlays or {}).items():
        s = series.reindex(df.index)
        fig.add_trace(go.Scatter(x=x_labels, y=s, mode="lines", name=label))

    fig.update_layout(
        title=title,
        template=_TPL,
        height=height,
        xaxis_type="category",
        xaxis_rangeslider_visible=False,
        showlegend=True,
    )
    fig.update_xaxes(tickangle=-45, showspikes=True, spikemode="across")
    return _maybe_save(fig, out)


def oi_histogram(
    chain_df: pd.DataFrame,
    *,
    title: str = "Option Chain OI",
    out: str | Path | None = None,
) -> go.Figure:
    """Side-by-side CE / PE Open Interest histogram by strike.

    Pass the long-format DataFrame from `option_analytics.chain_to_df`.
    """
    ce = chain_df[chain_df["side"] == "CE"][["strike", "oi"]].sort_values("strike")
    pe = chain_df[chain_df["side"] == "PE"][["strike", "oi"]].sort_values("strike")
    fig = go.Figure([
        go.Bar(x=ce["strike"], y=ce["oi"], name="CE OI", marker_color="#26a69a"),
        go.Bar(x=pe["strike"], y=pe["oi"], name="PE OI", marker_color="#ef5350"),
    ])
    underlying = chain_df.attrs.get("underlying_ltp")
    if underlying:
        fig.add_vline(x=underlying, line_dash="dash", line_color="white",
                      annotation_text=f"Spot {underlying}", annotation_position="top right")
    fig.update_layout(
        title=title,
        template=_TPL,
        barmode="group",
        xaxis_title="Strike",
        yaxis_title="Open Interest",
        height=600,
    )
    return _maybe_save(fig, out)


def heatmap(
    matrix: pd.DataFrame,
    *,
    title: str = "",
    color_scale: str = "RdYlGn",
    out: str | Path | None = None,
    annotate: bool = True,
) -> go.Figure:
    """Sector / constituent heatmap.

    `matrix` rows = symbols, columns = a single metric (or use treemap-
    style with one column).
    """
    fig = go.Figure(go.Heatmap(
        z=matrix.values,
        x=list(matrix.columns),
        y=list(matrix.index),
        colorscale=color_scale,
        zmid=0,
        text=matrix.round(2).values if annotate else None,
        texttemplate="%{text}" if annotate else None,
    ))
    fig.update_layout(title=title, template=_TPL, height=max(400, 18 * len(matrix)))
    return _maybe_save(fig, out)


def depth_ladder(
    depth_data: dict[str, Any],
    *,
    title: str = "Depth Ladder",
    out: str | Path | None = None,
) -> go.Figure:
    """Five / twenty / fifty-level book ladder, asks on top, bids on bottom.

    `depth_data` is the `data` block from `client.depth()`.
    """
    asks = pd.DataFrame(depth_data["asks"]).sort_values("price", ascending=False)
    bids = pd.DataFrame(depth_data["bids"]).sort_values("price", ascending=False)
    fig = go.Figure([
        go.Bar(y=asks["price"], x=asks["quantity"], name="Asks", orientation="h",
               marker_color="#ef5350"),
        go.Bar(y=bids["price"], x=bids["quantity"], name="Bids", orientation="h",
               marker_color="#26a69a"),
    ])
    ltp = depth_data.get("ltp")
    if ltp:
        fig.add_hline(y=ltp, line_dash="dash", line_color="white",
                      annotation_text=f"LTP {ltp}", annotation_position="right")
    fig.update_layout(title=title, template=_TPL, height=600, barmode="overlay")
    return _maybe_save(fig, out)


def payoff_chart(
    payoff_df: pd.DataFrame,
    *,
    title: str = "Strategy Payoff",
    out: str | Path | None = None,
) -> go.Figure:
    """Plot multi-leg payoff (output of `option_analytics.payoff`)."""
    fig = go.Figure(go.Scatter(
        x=payoff_df.index, y=payoff_df["payoff"], mode="lines",
        line=dict(width=3), name="Payoff",
        fill="tozeroy",
    ))
    fig.add_hline(y=0, line_color="white", line_dash="dot")
    fig.update_layout(title=title, template=_TPL, height=500,
                      xaxis_title="Spot at Expiry", yaxis_title="P&L per unit")
    return _maybe_save(fig, out)
