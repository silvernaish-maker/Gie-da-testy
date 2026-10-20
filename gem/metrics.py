"""Statystyki wyników: CAGR, zmienność, obsunięcie, Sharpe, wyniki roczne."""
import numpy as np
import pandas as pd


def monthly_returns(values: pd.Series) -> pd.Series:
    return values.pct_change().dropna()


def drawdown(values: pd.Series) -> pd.Series:
    return values / values.cummax() - 1


def annual_returns(values: pd.Series) -> pd.Series:
    """Stopy zwrotu w latach kalendarzowych (pierwszy i ostatni rok mogą być niepełne)."""
    year_end = values.groupby(values.index.year).last()
    prev = year_end.shift(1)
    prev.iloc[0] = values.iloc[0]
    return year_end / prev - 1


def summary(values: pd.Series, cash_returns: pd.Series | None = None) -> dict:
    r = monthly_returns(values)
    n = len(r)
    years = n / 12
    cagr = (values.iloc[-1] / values.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    vol = r.std() * np.sqrt(12)
    mdd = drawdown(values).min()
    sharpe = np.nan
    if cash_returns is not None:
        ex = r - cash_returns.reindex(r.index).fillna(0)
        if ex.std() > 0:
            sharpe = ex.mean() / ex.std() * np.sqrt(12)
    yearly = annual_returns(values)
    # pierwszy rok (start w trakcie roku) i niepełny ostatni nie są porównywalne
    full = yearly.iloc[1:]
    if values.index[-1].month != 12:
        full = full.iloc[:-1]
    return {
        "Od": values.index[0].strftime("%Y-%m"),
        "Do": values.index[-1].strftime("%Y-%m"),
        "Lata": round(years, 1),
        "CAGR": cagr,
        "Zmienność": vol,
        "Maks. obsunięcie": mdd,
        "Sharpe": sharpe,
        "Calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
        "Najlepszy rok": full.max() if len(full) else np.nan,
        "Najgorszy rok": full.min() if len(full) else np.nan,
        "Miesiące na plusie": (r > 0).mean(),
    }


def time_in_assets(holds: pd.Series) -> pd.Series:
    """Udział miesięcy spędzonych w każdym aktywie (bez ostatniego, niezrealizowanego)."""
    h = holds.iloc[:-1] if len(holds) > 1 else holds
    return h.value_counts(normalize=True)
