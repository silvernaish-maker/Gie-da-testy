"""Silnik GEM (Global Equity Momentum) na miesięcznych stopach zwrotu w PLN.

Reguły (Antonacci, w wersji opisanej przez inwestomat.eu, dostosowanej do
wybranych aktywów):

1. Na koniec każdego miesiąca liczymy stopę zwrotu z ostatnich N miesięcy
   (domyślnie 12) dla wszystkich ETF-ów.
2. Momentum absolutne: jeśli momentum aktywa referencyjnego (domyślnie
   S&P 500, tak jak w oryginale) jest wyższe niż momentum „gotówki”
   (ETFBCASH – polski odpowiednik amerykańskich T-bills), zostajemy w akcjach.
3. Momentum względne: w akcjach kupujemy ETF z najwyższym momentum spośród
   Nasdaq-100, S&P 500, WIG20TR, mWIG40TR i sWIG80TR.
4. W przeciwnym razie przechodzimy do obligacji – domyślnie do tej z trzech
   (długie / TBSP / krótkie), która ma najwyższe momentum; można też wskazać
   jedną stałą obligację.
5. Cały portfel jest zawsze w jednym ETF-ie, decyzja raz w miesiącu,
   transakcja po zamknięciu ostatniej sesji miesiąca.
"""
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from .config import ASSETS, BONDS, DEFAULTS, EQUITIES


@dataclass(frozen=True)
class Params:
    lookback: int = DEFAULTS["lookback"]
    abs_ref: str = DEFAULTS["abs_ref"]
    cash: str = DEFAULTS["cash"]
    defensive: str = DEFAULTS["defensive"]
    commission: float = DEFAULTS["commission"]
    fx_cost: float = DEFAULTS["fx_cost"]
    tax_rate: float = DEFAULTS["tax_rate"]
    equities: tuple = tuple(EQUITIES)
    bonds: tuple = tuple(BONDS)

    def with_(self, **kw):
        return replace(self, **kw)


def momentum(returns: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Skumulowana stopa zwrotu z ostatnich `lookback` miesięcy (NaN, gdy za krótka historia)."""
    return np.expm1(np.log1p(returns).rolling(lookback, min_periods=lookback).sum())


def decide(mom: pd.Series, p: Params):
    """Wybór aktywa na podstawie momentum z jednego końca miesiąca.

    Zwraca (klucz aktywa, opis decyzji) albo (None, powód), gdy brakuje danych.
    """
    eq = mom[list(p.equities)].dropna()
    if eq.empty or pd.isna(mom.get(p.cash)):
        return None, "za krótka historia"
    best_eq = eq.idxmax()
    ref_key = best_eq if p.abs_ref == "best" else p.abs_ref
    ref = mom.get(ref_key)
    if pd.isna(ref):
        return None, f"brak momentum dla {ref_key}"
    if ref > mom[p.cash]:
        return best_eq, "akcje"
    if p.defensive == "best_bond":
        bonds = mom[list(p.bonds)].dropna()
        return bonds.idxmax(), "obligacje"
    if pd.isna(mom.get(p.defensive)):
        return p.cash, "obligacje"
    return p.defensive, "obligacje"


def signals(returns: pd.DataFrame, p: Params, require_all: bool = True) -> pd.DataFrame:
    """Decyzja na koniec każdego miesiąca (aktywo trzymane w kolejnym miesiącu)."""
    mom = momentum(returns, p.lookback)
    universe = list(dict.fromkeys(list(p.equities) + list(p.bonds) + [p.cash]))
    rows = []
    for t, m in mom.iterrows():
        if require_all and m[universe].isna().any():
            rows.append((t, None, "za krótka historia"))
            continue
        choice, regime = decide(m, p)
        rows.append((t, choice, regime))
    return pd.DataFrame(rows, columns=["date", "hold", "regime"]).set_index("date")


@dataclass
class SimResult:
    name: str
    params: Params | None
    history: pd.DataFrame          # wartość portfela na koniec miesiąca i trzymane aktywo
    final_value: float             # przed likwidacją
    liquidation_value: float       # po sprzedaży, przewalutowaniu i podatku
    taxes_paid: float
    costs_paid: float
    switches: int
    extra: dict = field(default_factory=dict)

    @property
    def values(self) -> pd.Series:
        return self.history["value"]


def _fx_needed(a, b):
    ca = ASSETS[a].currency if a else "PLN"
    cb = ASSETS[b].currency if b else "PLN"
    return ca != cb


class _TaxBook:
    """Uproszczone rozliczenie podatku Belki: roczne saldo zysków i strat,
    stratę można odliczyć przez kolejne 5 lat."""

    def __init__(self, rate):
        self.rate = rate
        self.realized = {}
        self.losses = []  # [rok, pozostała strata]

    def add(self, year, gain):
        self.realized[year] = self.realized.get(year, 0.0) + gain

    def settle(self, year):
        net = self.realized.pop(year, 0.0)
        if net <= 0:
            if net < 0:
                self.losses.append([year, -net])
            return 0.0
        for item in self.losses:
            if year - item[0] > 5 or item[1] <= 0:
                continue
            used = min(item[1], net)
            item[1] -= used
            net -= used
        self.losses = [i for i in self.losses if i[1] > 0 and year - i[0] <= 5]
        return self.rate * net


def simulate(returns: pd.DataFrame, holds: pd.Series, p: Params, name="GEM",
             start_value=100_000.0) -> SimResult:
    """Symulacja portfela trzymającego co miesiąc jedno aktywo z `holds`.

    `holds` – indeks: koniec miesiąca, wartość: aktywo kupione na zamknięciu
    tego dnia (None = brak sygnału). Symulacja startuje od pierwszego sygnału.
    """
    holds = holds.dropna()
    if holds.empty:
        raise ValueError(f"{name}: brak sygnałów do symulacji")
    dates = returns.index[returns.index >= holds.index[0]]
    holds = holds.reindex(dates).ffill()

    tax = _TaxBook(p.tax_rate)
    value = start_value
    basis = 0.0
    held = None
    taxes = costs = 0.0
    switches = 0
    rows = []

    def trade(new, year):
        # przewalutowanie tylko przy zmianie waluty (USD->USD bez konwersji)
        nonlocal value, basis, held, costs, switches
        before = value
        if held is not None:
            value *= 1 - p.commission
            tax.add(year, value - basis)
            switches += 1
        if _fx_needed(held, new):
            value *= 1 - p.fx_cost
        basis = value
        value *= 1 - p.commission
        costs += before - value
        held = new

    for i, t in enumerate(dates):
        if i > 0 and held is not None:
            r = returns.at[t, held]
            if pd.isna(r):
                raise ValueError(f"{name}: brak zwrotu {held} w {t:%Y-%m}")
            value *= 1 + r
        target = holds.at[t]
        if target != held:
            trade(target, t.year)
        paid = 0.0
        last_in_year = i == len(dates) - 1 or dates[i + 1].year != t.year
        if p.tax_rate > 0 and last_in_year and i < len(dates) - 1:
            paid = tax.settle(t.year)
            if paid > 0:
                # podatek opłacamy, sprzedając część pozycji (to też realizuje zysk)
                frac = min(paid / value, 1.0)
                tax.add(t.year + 1, frac * (value - basis))
                basis *= 1 - frac
                value -= paid
                taxes += paid
        rows.append((t, value, held, paid))

    history = pd.DataFrame(rows, columns=["date", "value", "hold", "tax"]).set_index("date")

    # wartość po zamknięciu pozycji na koniec okresu (dla porównania z IKE)
    liq = value * (1 - p.commission)
    if _fx_needed(held, None):
        liq *= 1 - p.fx_cost
    final_tax = 0.0
    if p.tax_rate > 0:
        year = dates[-1].year
        tax.add(year, liq - basis)
        final_tax = tax.settle(year)
    return SimResult(
        name=name, params=p, history=history, final_value=value,
        liquidation_value=liq - final_tax, taxes_paid=taxes + final_tax,
        costs_paid=costs + (value - liq), switches=switches,
    )


def run_gem(returns: pd.DataFrame, p: Params, name="GEM", start=None, end=None):
    sig = signals(returns, p)
    if start is not None:
        sig = sig.loc[pd.Timestamp(start):]
    if end is not None:
        sig = sig.loc[:pd.Timestamp(end)]
        returns = returns.loc[:pd.Timestamp(end)]
    res = simulate(returns, sig["hold"], p, name=name)
    res.extra["signals"] = sig
    return res


def run_buy_and_hold(returns: pd.DataFrame, key: str, p: Params, start, end=None):
    r = returns.loc[:pd.Timestamp(end)] if end is not None else returns
    idx = r.index[r.index >= pd.Timestamp(start)]
    holds = pd.Series(key, index=idx)
    return simulate(r, holds, p, name=f"Kup i trzymaj: {ASSETS[key].name}")
