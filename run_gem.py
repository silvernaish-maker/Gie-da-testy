#!/usr/bin/env python3
"""Symulacja GEM: pobiera dane ze stooq, liczy sygnał, backtest, warianty i raport HTML.

Przykłady:
    python run_gem.py                      # domyślne reguły, raport w reports/
    python run_gem.py --refresh            # pobierz świeże notowania
    python run_gem.py --lookback 6 --defensive LONG --abs-ref best
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gem import report
from gem.backtest import Params, momentum, decide, run_buy_and_hold, run_gem, signals
from gem.config import ASSETS, BONDS, DEFAULTS, EQUITIES
from gem.data import StooqError, load_market_data
from gem.metrics import annual_returns, drawdown, summary, time_in_assets

ROOT = Path(__file__).resolve().parent
START_VALUE = 100_000.0


def cagr_from(value, years):
    return (value / START_VALUE) ** (1 / years) - 1 if years > 0 else np.nan


def describe(p: Params):
    abs_txt = "S&P 500 vs ETFBCASH" if p.abs_ref == "SPX" else (
        "najlepsze akcje vs ETFBCASH" if p.abs_ref == "best" else f"{ASSETS[p.abs_ref].name} vs ETFBCASH")
    def_txt = "najlepsza obligacja" if p.defensive == "best_bond" else ASSETS[p.defensive].name
    return abs_txt, def_txt


def run_pair(returns, p, name, start, end=None):
    """Ten sam wariant na IKE (bez podatku) i na zwykłym rachunku (Belka)."""
    ike = run_gem(returns, p.with_(tax_rate=0.0), name=name, start=start, end=end)
    taxed = run_gem(returns, p, name=name, start=start, end=end)
    return ike, taxed


def stats_row(name, ike, taxed, cash):
    s = summary(ike.values, cash)
    return {
        "name": name,
        "stats": s,
        "cagr_tax": cagr_from(taxed.liquidation_value, s["Lata"] if s["Lata"] else np.nan),
        "switches_per_year": ike.switches / s["Lata"] if s["Lata"] else None,
    }


def alloc_runs(hist: pd.DataFrame):
    holds, vals, dates = hist["hold"].tolist(), hist["value"].tolist(), hist.index
    runs, i = [], 0
    while i < len(holds):
        j = i
        while j + 1 < len(holds) and holds[j + 1] == holds[i]:
            j += 1
        end = j + 1 if j + 1 < len(holds) else j
        runs.append({
            "hold": holds[i],
            "from": dates[i].strftime("%Y-%m"),
            "to": dates[end].strftime("%Y-%m"),
            "months": j - i + 1,
            "ret": vals[end] / vals[i] - 1,
        })
        i = j + 1
    return runs


def provenance_segments(prov: pd.Series):
    prov = prov.dropna()
    segs = []
    for date, label in prov.items():
        if segs and segs[-1]["label"] == label:
            segs[-1]["to"] = date.strftime("%Y-%m")
        else:
            segs.append({"label": label, "from": date.strftime("%Y-%m"), "to": date.strftime("%Y-%m")})
    return segs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="pobierz ponownie dane ze stooq")
    ap.add_argument("--lookback", type=int, default=DEFAULTS["lookback"])
    ap.add_argument("--abs-ref", default=DEFAULTS["abs_ref"], help="SPX (domyślnie) albo best")
    ap.add_argument("--defensive", default=DEFAULTS["defensive"],
                    help="best_bond (domyślnie) albo LONG / TBSP / CASH")
    ap.add_argument("--commission", type=float, default=DEFAULTS["commission"])
    ap.add_argument("--fx-cost", type=float, default=DEFAULTS["fx_cost"])
    ap.add_argument("--tax", type=float, default=DEFAULTS["tax_rate"])
    ap.add_argument("--start", help="najwcześniejsza data startu (RRRR-MM)")
    ap.add_argument("--end", help="koniec symulacji (RRRR-MM)")
    ap.add_argument("--out", default=str(ROOT / "reports" / "gem_raport.html"))
    ap.add_argument("--fragment", action="store_true",
                    help="zapisz raport bez szkieletu <html> (do publikacji jako strona Claude)")
    args = ap.parse_args()

    print("Pobieram/wczytuję notowania...")
    try:
        md = load_market_data(refresh=args.refresh)
    except StooqError as e:
        sys.exit(f"\nBŁĄD: {e}")
    print("\nŹródła danych (miesięczne stopy zwrotu):")
    for k, a in ASSETS.items():
        segs = provenance_segments(md.provenance[k])
        print(f"  {a.name:18s} " + "; ".join(f"{g['label']} {g['from']}–{g['to']}" for g in segs))
    returns = md.returns
    if args.end:
        returns = returns.loc[:pd.Timestamp(args.end) + pd.offsets.MonthEnd(0)]
    p = Params(lookback=args.lookback, abs_ref=args.abs_ref, defensive=args.defensive,
               commission=args.commission, fx_cost=args.fx_cost, tax_rate=args.tax)
    cash = returns["CASH"]

    # --- główny wariant -------------------------------------------------------
    start = pd.Timestamp(args.start) + pd.offsets.MonthEnd(0) if args.start else None
    gem_ike, gem_tax = run_pair(returns, p, "GEM", start)
    t0 = gem_ike.history.index[0]
    end = gem_ike.history.index[-1]
    sig = gem_ike.extra["signals"]

    rows = [stats_row("GEM (strategia)", gem_ike, gem_tax, cash)]
    bh = {}
    for key in ASSETS:
        a = run_buy_and_hold(returns, key, p.with_(tax_rate=0.0), t0)
        b = run_buy_and_hold(returns, key, p, t0)
        bh[key] = a
        rows.append(stats_row(ASSETS[key].name, a, b, cash))

    # --- warianty -------------------------------------------------------------
    grid = [("Główny", p, True)]
    alt_abs = "best" if p.abs_ref != "best" else "SPX"
    grid.append(("Filtr na najlepszym indeksie" if alt_abs == "best" else "Filtr na S&P 500",
                 p.with_(abs_ref=alt_abs), False))
    for d in ["best_bond", "LONG", "TBSP", "CASH"]:
        if d != p.defensive:
            grid.append((f"Obrona: {'najlepsza obligacja' if d == 'best_bond' else ASSETS[d].name}",
                         p.with_(defensive=d), False))
    for lb in [3, 6, 9, 12]:
        if lb != p.lookback:
            grid.append((f"Okno {lb} mies.", p.with_(lookback=lb), False))
    grid.append(("Tylko USA (Nasdaq, S&P)", p.with_(equities=("NDX", "SPX")), False))
    grid.append(("Tylko GPW (WIG20/mWIG40/sWIG80)", p.with_(equities=("W20", "M40", "S80"), abs_ref="best"), False))
    grid.append(("Bez kosztów", p.with_(commission=0.0, fx_cost=0.0), False))

    variants = []
    for name, vp, is_main in grid:
        ike, taxed = (gem_ike, gem_tax) if is_main else run_pair(returns, vp, name, t0)
        s = summary(ike.values, cash)
        abs_txt, def_txt = describe(vp)
        variants.append({
            "name": name, "main": is_main, "lookback": vp.lookback, "abs": abs_txt, "def": def_txt,
            "cagr": s["CAGR"], "cagr_tax": cagr_from(taxed.liquidation_value, s["Lata"]),
            "mdd": s["Maks. obsunięcie"], "sharpe": s["Sharpe"],
            "switches_per_year": ike.switches / s["Lata"],
        })

    # --- bieżący sygnał ---------------------------------------------------------
    last = sig.iloc[-1]
    prev = sig.iloc[-2]["hold"] if len(sig) > 1 else None
    mom_all = momentum(returns, p.lookback)
    mom_last = mom_all.iloc[-1]
    asof = sig.index[-1]
    signal = {
        "asof_txt": f"{report.PL_MONTHS_GEN[asof.month - 1]} {asof.year}",
        "hold": last["hold"], "regime": last["regime"], "prev_hold": prev,
        "lookback": p.lookback,
        "mom": {k: (None if pd.isna(v) else float(v)) for k, v in mom_last.items()},
    }
    live = None
    if md.partial_date is not None and not md.partial.isna().all():
        ext = pd.concat([returns, md.partial.to_frame().T])
        live_mom = momentum(ext, p.lookback).iloc[-1]
        live_hold, live_regime = decide(live_mom, p)
        if live_hold:
            live = {"hold": live_hold, "regime": live_regime, "date_txt": report.day_pl(md.partial_date)}
            signal["live_mom"] = {k: (None if pd.isna(v) else float(v)) for k, v in live_mom.items()}
            signal["live_date"] = md.partial_date.strftime("%d.%m.%Y")

    # --- dane do wykresów ---------------------------------------------------------
    slots = {k: i + 1 for i, k in enumerate(ASSETS)}
    assets_ctx = [{"key": k, "name": a.name, "ticker": a.ticker, "kind": a.kind, "slot": slots[k]}
                  for k, a in ASSETS.items()]
    dates = [d.strftime("%Y-%m") for d in gem_ike.values.index]
    growth_keys = ["SPX", "NDX", "W20", "TBSP"]
    growth = {"dates": dates, "series": [{"key": "GEM", "label": "GEM", "values": gem_ike.values.round(0).tolist()}]
              + [{"key": k, "label": ASSETS[k].name, "values": bh[k].values.round(0).tolist()} for k in growth_keys]}
    dd = {"dates": dates, "series": [
        {"key": "GEM", "label": "GEM", "values": drawdown(gem_ike.values).round(4).tolist()},
        {"key": "SPX", "label": "S&P 500", "values": drawdown(bh["SPX"].values).round(4).tolist()},
    ]}

    # --- wyniki roczne ------------------------------------------------------------
    ann_cols = ["GEM", "Pozycje"] + [ASSETS[k].name for k in ASSETS]
    gem_ann = annual_returns(gem_ike.values)
    bh_ann = {k: annual_returns(v.values) for k, v in bh.items()}
    hist = gem_ike.history
    ann_rows = []
    for year in gem_ann.index[1:] if len(gem_ann) > 1 else gem_ann.index:
        # pozycje trzymane w trakcie roku (decyzje z grudnia poprzedniego roku do listopada)
        mask = (hist.index > pd.Timestamp(year - 1, 12, 1)) & (hist.index < pd.Timestamp(year, 12, 1))
        held = list(dict.fromkeys(ASSETS[h].short for h in hist.loc[mask, "hold"]))
        label = str(year) if not (year == end.year and end.month != 12) else f"{year} (do {end.month:02d})"
        ann_rows.append({"year": label, "values": [float(gem_ann[year]), ", ".join(held)]
                         + [float(bh_ann[k].get(year, np.nan)) for k in ASSETS]})

    # --- ostatnie zmiany ------------------------------------------------------------
    sw = sig.dropna(subset=["hold"])
    changes = sw[sw["hold"] != sw["hold"].shift(1)].iloc[1:]
    sw_rows = []
    for d, r in changes.iloc[::-1].head(15).iterrows():
        prev_hold = sw["hold"].shift(1).loc[d]
        m = mom_all.loc[d]
        sw_rows.append([
            report.esc(f"{report.PL_MONTHS[d.month - 1]} {d.year}"),
            report.esc(ASSETS[prev_hold].name), report.esc(ASSETS[r["hold"]].name),
            report.esc(r["regime"]), report.pct(m[r["hold"]]),
            report.pct(m["SPX"]), report.pct(m["CASH"]),
        ])
    switches_html = report._table(
        ["Koniec miesiąca", "Sprzedaż", "Kupno", "Tryb", "Momentum kupionego", "Momentum S&P 500", "Momentum ETFBCASH"],
        sw_rows)

    lookback_start = t0 - pd.offsets.MonthEnd(p.lookback)
    provenance = [{"name": a.name, "ticker": a.ticker,
                   "segments": provenance_segments(md.provenance.loc[lookback_start:end, k])}
                  for k, a in ASSETS.items()]

    ctx = {
        "generated": dt.date.today().strftime("%d.%m.%Y"),
        "data_last": md.last_date.strftime("%d.%m.%Y"),
        "params": {"lookback": p.lookback, "commission": p.commission, "fx_cost": p.fx_cost, "tax_rate": p.tax_rate},
        "assets": assets_ctx, "signal": signal, "live": live,
        "growth": growth, "drawdown": dd, "alloc": alloc_runs(hist),
        "summary": rows,
        "annual": {"columns": ann_cols, "rows": ann_rows},
        "variants": variants, "provenance": provenance, "switches_html": switches_html,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    page = report.render(ctx)
    if not args.fragment:
        page = report.standalone(page)
    out.write_text(page, encoding="utf-8")

    # --- CSV z historią sygnałów ------------------------------------------------------
    csv = mom_all.loc[t0:end].add_prefix("mom_").round(4)
    csv.insert(0, "decyzja", sig.loc[t0:end, "hold"])
    csv.insert(1, "tryb", sig.loc[t0:end, "regime"])
    csv["wartosc_IKE"] = gem_ike.values.round(2)
    csv["wartosc_Belka"] = gem_tax.values.round(2)
    csv.index.name = "koniec_miesiaca"
    csv.to_csv(out.with_name("gem_sygnaly.csv"), encoding="utf-8-sig")

    # --- podsumowanie w konsoli --------------------------------------------------------
    s = rows[0]["stats"]
    print(f"\nOkres: {s['Od']} – {s['Do']} ({s['Lata']} lat), start {START_VALUE:,.0f} zł")
    print(f"{'Portfel':38s} {'CAGR IKE':>9s} {'po Belce':>9s} {'MaxDD':>8s} {'Sharpe':>7s}")
    for r in rows:
        st = r["stats"]
        print(f"{r['name']:38s} {st['CAGR']:9.2%} {r['cagr_tax']:9.2%} {st['Maks. obsunięcie']:8.1%} {st['Sharpe']:7.2f}")
    print("\nWarianty:")
    for v in variants:
        print(f"  {v['name']:38s} CAGR {v['cagr']:7.2%}  po Belce {v['cagr_tax']:7.2%}  "
              f"MaxDD {v['mdd']:7.1%}  zmian/rok {v['switches_per_year']:.1f}")
    print(f"\nSygnał na koniec {signal['asof_txt']}: {ASSETS[last['hold']].ticker} ({last['regime']})")
    if live:
        print(f"Wstępnie na {live['date_txt']}: {ASSETS[live['hold']].ticker}")
    print("Czas w aktywach:", ", ".join(f"{ASSETS[k].name} {v:.0%}" for k, v in time_in_assets(hist['hold']).items()))
    print(f"\nRaport: {out}")


if __name__ == "__main__":
    main()
