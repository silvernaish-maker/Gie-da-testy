"""Testy logiki GEM na sztucznych danych (nie są to dane rynkowe)."""
import numpy as np
import pandas as pd
import pytest

from gem.backtest import Params, _TaxBook, decide, momentum, signals, simulate
from gem.data import bond_return_from_yields
from gem.metrics import annual_returns, drawdown, summary

KEYS = ["NDX", "SPX", "W20", "M40", "S80", "LONG", "TBSP", "CASH"]


def frame(n=30, **monthly):
    idx = pd.date_range("2010-01-31", periods=n, freq="ME")
    data = {k: monthly.get(k, 0.0) for k in KEYS}
    return pd.DataFrame({k: np.full(n, v, dtype=float) for k, v in data.items()}, index=idx)


def test_momentum_compounds_lookback_window():
    r = frame(n=13, SPX=0.01)
    m = momentum(r, 12)
    assert m["SPX"].iloc[:11].isna().all()
    assert m["SPX"].iloc[11] == pytest.approx(1.01 ** 12 - 1)


def test_picks_best_equity_when_sp500_beats_cash():
    m = pd.Series({"NDX": 0.30, "SPX": 0.10, "W20": 0.20, "M40": 0.0, "S80": -0.1,
                   "LONG": 0.05, "TBSP": 0.04, "CASH": 0.05})
    assert decide(m, Params()) == ("NDX", "akcje")


def test_goes_to_best_bond_when_sp500_below_cash():
    m = pd.Series({"NDX": 0.30, "SPX": 0.04, "W20": 0.20, "M40": 0.0, "S80": -0.1,
                   "LONG": 0.08, "TBSP": 0.06, "CASH": 0.05})
    assert decide(m, Params()) == ("LONG", "obligacje")
    # wariant, w którym filtr absolutny dotyczy najlepszego indeksu akcji
    assert decide(m, Params(abs_ref="best")) == ("NDX", "akcje")
    # stała obligacja w obronie
    assert decide(m, Params(defensive="TBSP")) == ("TBSP", "obligacje")


def test_signals_wait_for_full_history():
    r = frame(n=14, NDX=0.02, SPX=0.01, CASH=0.002)
    s = signals(r, Params())
    assert s["hold"].iloc[:11].isna().all()
    assert (s["hold"].iloc[11:] == "NDX").all()


def test_simulation_without_costs_matches_compounded_return():
    r = frame(n=24, NDX=0.02, SPX=0.01, CASH=0.002)
    p = Params(commission=0, fx_cost=0, tax_rate=0)
    res = simulate(r, pd.Series("NDX", index=r.index), p)
    assert res.final_value == pytest.approx(100_000 * 1.02 ** 23)
    assert res.liquidation_value == pytest.approx(res.final_value)
    assert res.switches == 0


def test_costs_apply_fx_only_when_currency_changes():
    r = frame(n=3)
    p = Params(commission=0.01, fx_cost=0.02, tax_rate=0)
    holds = pd.Series(["NDX", "SPX", "W20"], index=r.index)  # USD -> USD -> PLN
    res = simulate(r, holds, p)
    # kupno NDX: fx+prowizja; NDX->SPX: 2x prowizja; SPX->W20: 2x prowizja + fx
    expected = 100_000 * 0.98 * 0.99 * 0.99 * 0.99 * 0.99 * 0.98 * 0.99
    assert res.final_value == pytest.approx(expected)
    # likwidacja W20 (PLN): tylko prowizja
    assert res.liquidation_value == pytest.approx(expected * 0.99)


def test_tax_book_offsets_losses_for_five_years():
    book = _TaxBook(0.19)
    book.add(2010, -1000)
    assert book.settle(2010) == 0
    book.add(2011, 600)
    assert book.settle(2011) == 0
    book.add(2012, 1000)
    assert book.settle(2012) == pytest.approx(0.19 * 600)
    book.add(2020, -500)
    book.settle(2020)
    book.add(2026, 500)  # strata z 2020 przedawniona po 5 latach
    assert book.settle(2026) == pytest.approx(0.19 * 500)


def test_tax_is_paid_at_year_end_after_profitable_switch():
    idx = pd.date_range("2010-10-31", periods=6, freq="ME")
    r = pd.DataFrame(0.0, index=idx, columns=KEYS)
    r.loc[idx[1], "NDX"] = 0.10
    holds = pd.Series(["NDX", "NDX", "W20", "W20", "W20", "W20"], index=idx)
    p = Params(commission=0, fx_cost=0, tax_rate=0.19)
    res = simulate(r, holds, p)
    # zysk 10 000 zł zrealizowany w listopadzie, podatek 1 900 zł w grudniu
    assert res.history.loc["2010-12-31", "tax"] == pytest.approx(1900)
    assert res.final_value == pytest.approx(110_000 - 1900)


def test_synthetic_bond_return_is_coupon_when_yield_unchanged():
    y = pd.Series([6.0, 6.0], index=pd.date_range("2010-01-31", periods=2, freq="ME"))
    r = bond_return_from_yields(y, 10)
    assert r.iloc[0] == pytest.approx(0.06 / 12, rel=0.02)


def test_synthetic_bond_loses_when_yield_rises():
    y = pd.Series([5.0, 6.0], index=pd.date_range("2010-01-31", periods=2, freq="ME"))
    r = bond_return_from_yields(y, 10)
    # duracja ~7.7 => ok. -7.3% (+ kupon)
    assert -0.08 < r.iloc[0] < -0.06


def test_metrics():
    v = pd.Series([100, 110, 99, 121], index=pd.date_range("2010-10-31", periods=4, freq="ME"))
    assert drawdown(v).min() == pytest.approx(-0.1)
    yr = annual_returns(v)
    assert yr.loc[2010] == pytest.approx(-0.01)  # 99/100 - 1
    assert yr.loc[2011] == pytest.approx(121 / 99 - 1)
    s = summary(v)
    assert s["Maks. obsunięcie"] == pytest.approx(-0.1)
