"""Buy-and-hold indexes over a group of stocks (a sector or an industry).

The index is a portfolio bought on the first day of the window and then left
alone, so its weights drift with prices:

* market cap weighted - each stock bought at its share of the group's market
  cap that day. Holding it is the same as following a cap-weighted index while
  share counts stay put.
* equally weighted - 1/N of the money in each stock. Only equal on the first
  day: nothing is rebalanced, so over a long window the winners come to dominate.

Membership changes are the only trades:

* a stock that leaves (delisted, or its prices simply end) is sold at its last
  price, and the proceeds go to the remaining stocks in proportion to what is
  held in each. The survivors' weights relative to each other are untouched.
* a stock that joins (listed during the window, or - cap weighted - the first
  day it has a market cap) is bought at its weight that day: its share of the
  group's market cap, or 1/N with N counting it. The money comes from selling
  the same fraction of every current holding.

Prices are total-return closes in USD, so dividends are reinvested in the
stock that paid them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

CAP = "cap"
EQUAL = "equal"


@dataclass
class GroupIndex:
    level: pd.Series  # growth multiple, 1.0 on the first day the index holds anything
    n_held: pd.Series  # stocks held each day
    members: pd.DataFrame  # one row per stock held at any point in the window
    n_left_out: int  # priced in the window but never eligible (cap weighted: no market cap)


def build(prices: pd.DataFrame, caps: pd.DataFrame, start, end, method: str) -> GroupIndex:
    """Index over [start, end] from wide USD prices and caps (see data.get_price_panel).

    Prices must be continuous within each ticker's life, so that a ticker's held
    period is one unbroken run and every exit is a real end of prices.
    """
    prices = prices.loc[start:end]
    caps = caps.loc[start:end]
    dates = prices.index

    P = prices.to_numpy(dtype=float)
    C = caps.to_numpy(dtype=float)
    alive = ~np.isnan(P)
    eligible = alive & (C > 0) if method == CAP else alive

    ever = eligible.any(axis=0)
    n_left_out = int((alive.any(axis=0) & ~ever).sum())
    P, C, alive, eligible = P[:, ever], C[:, ever], alive[:, ever], eligible[:, ever]
    tickers = prices.columns[ever]
    T, N = P.shape

    if N == 0:
        empty = pd.Series(dtype=float)
        return GroupIndex(empty, empty, pd.DataFrame(), n_left_out)

    entry = eligible.argmax(axis=0)
    exit_ = T - alive[::-1].argmax(axis=0)  # one past the last priced day; T = held to the end
    entry_weight = np.full(N, np.nan)

    level = np.full(T, np.nan)
    n_held = np.zeros(T, dtype=int)
    units = np.zeros(N)
    held = np.zeros(N, dtype=bool)
    value = np.nan

    # Between two membership changes the holdings are fixed, so a whole segment
    # is one matrix product; only the change days need individual attention.
    events = np.unique(np.concatenate([entry, exit_[exit_ < T]]))
    bounds = np.append(events, T)
    for s, e in zip(bounds[:-1], bounds[1:]):
        if held.any():
            value = level[s - 1]
            survivors = held & (exit_ != s)
            before = units[survivors] @ P[s - 1, survivors]
            after = units[survivors] @ P[s, survivors]
            if before > 0:
                # The leavers' value moves to the survivors: the index carries on
                # at the survivors' own return from yesterday to today.
                value *= after / before
                units[survivors] *= value / after
            units[~survivors] = 0.0
            held = survivors

        joining = entry == s
        if joining.any():
            if np.isnan(value):
                value = 1.0
            if method == CAP:
                weights = C[s, joining] / np.nansum(C[s, held | joining])
            else:
                weights = np.full(joining.sum(), 1.0 / (held.sum() + joining.sum()))
            units[held] *= 1.0 - weights.sum()
            units[joining] = value * weights / P[s, joining]
            entry_weight[joining] = weights
            held |= joining

        if held.any():
            level[s:e] = P[s:e][:, held] @ units[held]
        else:
            level[s:e] = value  # everything left and nothing joined yet: cash
        n_held[s:e] = held.sum()

    last = np.minimum(exit_, T) - 1
    columns = np.arange(N)
    end_weight = np.where(held, units * P[-1] / level[-1], np.nan)
    members = pd.DataFrame(
        {
            "ticker": tickers,
            "market_cap": C[last, columns],
            "entry_weight": entry_weight,
            "end_weight": end_weight,
            "change": P[last, columns] / P[entry, columns] - 1,
            "joined": dates[entry].where(entry > 0),
            "left": dates[last].where(exit_ < T),
        }
    )
    return GroupIndex(
        level=pd.Series(level, index=dates),
        n_held=pd.Series(n_held, index=dates),
        members=members,
        n_left_out=n_left_out,
    )
