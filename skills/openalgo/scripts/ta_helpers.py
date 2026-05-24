"""Ergonomic wrappers combining TA-Lib and `openalgo.ta`.

Indicator rule (shared with vectorbt-backtesting-skills):
- TA-Lib for standard set: EMA, SMA, RSI, MACD, ATR, BBANDS, ADX, STDDEV, MOM
- openalgo.ta for specialty + signal helpers: supertrend, donchian,
  ichimoku, hma, kama, alma, zlema, vwma + exrem, crossover, crossunder, flip

This module hides the (close.values, talib_call, wrap-back-into-Series)
boilerplate that otherwise repeats in every example.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import talib as tl
from openalgo import ta


def ema(close: pd.Series, period: int) -> pd.Series:
    return pd.Series(tl.EMA(close.values, timeperiod=period), index=close.index, name=f"EMA{period}")


def sma(close: pd.Series, period: int) -> pd.Series:
    return pd.Series(tl.SMA(close.values, timeperiod=period), index=close.index, name=f"SMA{period}")


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    return pd.Series(tl.RSI(close.values, timeperiod=period), index=close.index, name=f"RSI{period}")


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    return pd.Series(
        tl.ATR(high.values, low.values, close.values, timeperiod=period),
        index=close.index, name=f"ATR{period}",
    )


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    m, s, h = tl.MACD(close.values, fastperiod=fast, slowperiod=slow, signalperiod=signal)
    return pd.DataFrame({"macd": m, "signal": s, "hist": h}, index=close.index)


def bbands(
    close: pd.Series,
    period: int = 20,
    stddev: float = 2.0,
) -> pd.DataFrame:
    u, m, l = tl.BBANDS(close.values, timeperiod=period, nbdevup=stddev, nbdevdn=stddev)
    return pd.DataFrame({"upper": u, "mid": m, "lower": l}, index=close.index)


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    return pd.Series(
        tl.ADX(high.values, low.values, close.values, timeperiod=period),
        index=close.index, name=f"ADX{period}",
    )


def stddev(close: pd.Series, period: int = 20) -> pd.Series:
    return pd.Series(tl.STDDEV(close.values, timeperiod=period), index=close.index)


def mom(close: pd.Series, period: int = 10) -> pd.Series:
    return pd.Series(tl.MOM(close.values, timeperiod=period), index=close.index)


# openalgo.ta wrappers ------------------------------------------------------


def supertrend(
    high: pd.Series, low: pd.Series, close: pd.Series,
    period: int = 10, multiplier: float = 3.0,
) -> tuple[pd.Series, pd.Series]:
    """Returns (supertrend_line, direction_series). direction = +1 long, -1 short."""
    line, direction = ta.supertrend(high, low, close, period=period, multiplier=multiplier)
    return line, direction


def donchian(
    high: pd.Series, low: pd.Series, period: int = 20
) -> tuple[pd.Series, pd.Series, pd.Series]:
    upper, lower, mid = ta.donchian(high, low, period=period)
    return upper, lower, mid


def ichimoku(
    high: pd.Series, low: pd.Series, close: pd.Series,
    tenkan: int = 9, kijun: int = 26, senkou_b: int = 52,
) -> pd.DataFrame:
    t, k, sa, sb, chikou = ta.ichimoku(high, low, close,
                                       tenkan_period=tenkan,
                                       kijun_period=kijun,
                                       senkou_b_period=senkou_b)
    return pd.DataFrame({
        "tenkan": t, "kijun": k, "senkou_a": sa, "senkou_b": sb, "chikou": chikou,
    })


def hma(close: pd.Series, period: int = 21) -> pd.Series:
    return ta.hma(close, period=period)


def kama(close: pd.Series, period: int = 10) -> pd.Series:
    return ta.kama(close, period=period)


def alma(close: pd.Series, period: int = 9, offset: float = 0.85, sigma: float = 6.0) -> pd.Series:
    return ta.alma(close, period=period, offset=offset, sigma=sigma)


def zlema(close: pd.Series, period: int = 14) -> pd.Series:
    return ta.zlema(close, period=period)


def vwma(close: pd.Series, volume: pd.Series, period: int = 20) -> pd.Series:
    return ta.vwma(close, volume, period=period)


# Signal helpers ------------------------------------------------------------


def clean_signals(buy_raw: pd.Series, sell_raw: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Apply `ta.exrem` in both directions; coerce NaN to False first.

    Returns (entries, exits) ready for `vbt.Portfolio.from_signals`.
    """
    b = buy_raw.fillna(False).astype(bool)
    s = sell_raw.fillna(False).astype(bool)
    return ta.exrem(b, s), ta.exrem(s, b)


def crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    return ta.crossover(a, b)


def crossunder(a: pd.Series, b: pd.Series) -> pd.Series:
    return ta.crossunder(a, b)


def flip(trigger_on: pd.Series, trigger_off: pd.Series) -> pd.Series:
    return ta.flip(trigger_on, trigger_off)
