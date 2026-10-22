"""Pobieranie notowań ze stooq.pl i budowa miesięcznych stóp zwrotu w PLN.

Surowe pliki CSV trafiają do data/raw/ (pobierane raz, odświeżane flagą
--refresh). Od 2026 r. stooq wymaga do pobierania CSV darmowego klucza API:
skrypt poprosi o niego przy pierwszym pobraniu i zapisze w stooq_apikey.txt
(można go też podać w zmiennej środowiskowej STOOQ_APIKEY). Pliki CSV
pobrane ręcznie ze strony stooq można wrzucić do data/raw/ pod nazwą
symbolu, np. data/raw/cspx.uk.csv albo data/raw/^tbsp.csv.
"""
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

from .config import ASSETS, FX_SYMBOLS, Source

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = Path(os.environ.get("GEM_DATA_DIR") or ROOT / "data" / "raw")
APIKEY_FILE = ROOT / "stooq_apikey.txt"
APIKEY_PAGE = "https://stooq.pl/q/d/?s=usdpln&get_apikey"
STOOQ_URLS = (
    "https://stooq.pl/q/d/l/?s={sym}&i=d",
    "https://stooq.com/q/d/l/?s={sym}&i=d",
)
HEADERS = {"User-Agent": "Mozilla/5.0 (gem-simulation)"}

_apikey = None
_asked = False


class StooqError(RuntimeError):
    pass


def _raw_path(symbol: str) -> Path:
    return RAW_DIR / f"{symbol.lower()}.csv"


def _parse_csv(path: Path) -> pd.Series:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    date_col = cols.get("data") or cols.get("date")
    close_col = cols.get("zamkniecie") or cols.get("close")
    if date_col is None or close_col is None:
        raise StooqError(f"{path.name}: nieznany format pliku ({list(df.columns)})")
    s = pd.Series(
        pd.to_numeric(df[close_col], errors="coerce").values,
        index=pd.to_datetime(df[date_col]),
        name=path.stem,
    )
    return s.dropna().sort_index()


def _clean_key(text: str) -> str:
    """Klucz z wklejonego tekstu – sam klucz albo cały link z „apikey=...”."""
    m = re.search(r"apikey=([A-Za-z0-9]+)", text)
    return m.group(1) if m else text.strip().strip('"\'')


def _page_text(html_text: str) -> str:
    txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def _load_apikey():
    global _apikey
    if _apikey is None:
        key = os.environ.get("STOOQ_APIKEY", "")
        if not key and APIKEY_FILE.exists():
            key = APIKEY_FILE.read_text(encoding="utf-8")
        _apikey = _clean_key(key) if key.strip() else ""
    return _apikey


def _ask_apikey(reason: str) -> str:
    """Prosi o klucz API stooq (raz na uruchomienie) i zapisuje go do pliku."""
    global _apikey, _asked
    instructions = (
        f"\n{reason}\n"
        "Stooq wymaga darmowego klucza API do pobierania plików CSV. Jak go zdobyć:\n"
        f"  1. Otwórz w przeglądarce: {APIKEY_PAGE}\n"
        "  2. Przepisz kod z obrazka (captcha) i zatwierdź.\n"
        "  3. Na dole strony pojawi się link „Pobierz dane w pliku .csv” – kliknij go\n"
        "     prawym przyciskiem, wybierz „Kopiuj adres linku” i wklej tutaj.\n"
        "     (Wystarczy też sam klucz, czyli tekst po „apikey=”.)\n"
    )
    if _asked or not sys.stdin or not sys.stdin.isatty():
        raise StooqError(instructions + f"Zapisz klucz w pliku {APIKEY_FILE} i uruchom ponownie.")
    _asked = True
    print(instructions)
    key = _clean_key(input("Wklej link albo klucz i naciśnij Enter: "))
    if not key:
        raise StooqError("Nie podano klucza API stooq.")
    APIKEY_FILE.write_text(key + "\n", encoding="utf-8")
    print(f"Zapisano klucz w {APIKEY_FILE.name}. Pobieram dalej...\n")
    _apikey = key
    return key


def fetch(symbol: str, refresh: bool = False) -> pd.Series | None:
    """Dzienne zamknięcia dla symbolu stooq (z cache w data/raw/)."""
    path = _raw_path(symbol)
    if path.exists() and not refresh:
        return _parse_csv(path)
    errors = []
    print(f"  pobieram {symbol}")
    for attempt in range(2):
        key = _load_apikey()
        needs_key = False
        for url in STOOQ_URLS:
            full = url.format(sym=quote(symbol)) + (f"&apikey={key}" if key else "")
            try:
                r = requests.get(full, headers=HEADERS, timeout=30)
            except requests.RequestException as e:
                errors.append(f"{url.split('/')[2]}: {e.__class__.__name__}")
                continue
            text = r.text.strip()
            head = text[:200].lower()
            if r.ok and (head.startswith("data,") or head.startswith("date,")):
                RAW_DIR.mkdir(parents=True, exist_ok=True)
                path.write_text(text + "\n", encoding="utf-8")
                return _parse_csv(path)
            if "limit" in head and "<" not in head[:1]:
                raise StooqError(f"stooq: przekroczony dzienny limit pobrań ({symbol}). Spróbuj jutro.")
            if head.startswith("<") and "apikey" in text.lower():
                needs_key = True
                break
            snippet = _page_text(text)[:80] if head.startswith("<") else text[:60]
            errors.append(f"{url.split('/')[2]}: HTTP {r.status_code} '{snippet}'")
        if not needs_key:
            break
        _ask_apikey("Stooq nie przyjął zapytania bez klucza API." if not key
                    else "Stooq odrzucił zapisany klucz API (wygasł albo jest błędny).")
    if path.exists():  # odświeżenie się nie udało – zostajemy przy starych danych
        return _parse_csv(path)
    print(f"  [brak danych] {symbol}: {'; '.join(errors) or 'brak odpowiedzi'}")
    return None


def fetch_first(symbols, refresh=False):
    for sym in symbols:
        s = fetch(sym, refresh)
        if s is not None and len(s) > 0:
            return sym, s
    return None, None


def to_monthly(daily: pd.Series) -> pd.Series:
    """Ostatnie zamknięcie w każdym miesiącu, indeksowane końcem miesiąca."""
    m = daily.resample("ME").last()
    return m.dropna()


def bond_return_from_yields(y: pd.Series, maturity: float) -> pd.Series:
    """Miesięczny zwrot całkowity syntetycznej obligacji o stałej zapadalności.

    Na koniec miesiąca t-1 kupujemy obligację po nominale z kuponem równym
    bieżącej rentowności, po miesiącu wyceniamy ją przy nowej rentowności
    (zapadalność krótsza o 1/12 roku) i doliczamy narosły kupon.
    """
    y = y / 100.0
    c = y.shift(1)
    t = maturity - 1 / 12
    disc = (1 + y) ** (-t)
    with np.errstate(divide="ignore", invalid="ignore"):
        annuity = np.where(np.abs(y) > 1e-9, (1 - disc) / y, t)
    price = c * annuity + disc
    return (price - 1 + c / 12).iloc[1:]


@dataclass
class MarketData:
    returns: pd.DataFrame       # miesięczne stopy zwrotu w PLN (kompletne miesiące)
    provenance: pd.DataFrame    # z jakiego źródła pochodzi zwrot w danym miesiącu
    partial: pd.Series          # zwrot bieżącego, niezakończonego miesiąca (lub pusty)
    partial_date: pd.Timestamp | None
    last_date: pd.Timestamp
    symbols_used: dict


def _source_returns(src: Source, ter: float, fx: dict, refresh: bool):
    sym, daily = fetch_first(src.symbols, refresh)
    if daily is None:
        return None, None
    monthly = to_monthly(daily)
    if src.kind == "price":
        r = monthly.pct_change(fill_method=None).iloc[1:]
        if src.currency != "PLN":
            fx_m = fx[src.currency]
            r = (1 + r) * (fx_m / fx_m.shift(1)).reindex(r.index) - 1
    elif src.kind == "yield":
        r = bond_return_from_yields(monthly, src.maturity)
    elif src.kind == "rate":
        r = (monthly.shift(1) / 100 / 12).iloc[1:]
    else:
        raise ValueError(src.kind)
    if src.proxy:
        r = r + (src.extra_annual - ter) / 12
    return sym, (r.dropna(), daily.index.max())


def load_market_data(refresh: bool = False) -> MarketData:
    fx, last_dates = {}, []
    for cur, syms in FX_SYMBOLS.items():
        _, daily = fetch_first(syms, refresh)
        if daily is None:
            raise StooqError(f"brak kursu {cur}/PLN – bez niego nie przeliczę ETF-ów z USD")
        fx[cur] = to_monthly(daily)
        last_dates.append(daily.index.max())

    rets, prov, used = {}, {}, {}
    for key, asset in ASSETS.items():
        combined = None
        label = pd.Series(dtype=object)
        for src in asset.sources:
            sym, res = _source_returns(src, asset.ter, fx, refresh)
            if res is None:
                continue
            r, last = res
            used.setdefault(key, []).append(sym)
            if combined is None:
                combined = r
                label = pd.Series(src.label, index=r.index)
                last_dates.append(last)
            else:
                # przybliżenie wypełnia tylko miesiące, których nie ma w lepszym źródle
                fill = r.index.difference(combined.index)
                fill = fill[fill < combined.index.min()] if len(combined) else fill
                combined = pd.concat([combined, r.loc[fill]]).sort_index()
                label = pd.concat([label, pd.Series(src.label, index=fill)]).sort_index()
        if combined is None:
            raise StooqError(f"brak jakichkolwiek danych dla {key} ({asset.ticker})")
        rets[key] = combined
        prov[key] = label

    returns = pd.DataFrame(rets).sort_index()
    provenance = pd.DataFrame(prov).reindex(returns.index)
    last_date = min(last_dates)

    # ostatni miesiąc jest niepełny, jeśli najnowsze wspólne notowanie nie jest
    # z ostatniej sesji miesiąca (31 grudnia GPW nie handluje)
    month_end = last_date + pd.offsets.MonthEnd(0)
    last_session = pd.offsets.BMonthEnd().rollforward(last_date)
    if last_session.month == 12 and last_session.day == 31:
        last_session -= pd.offsets.BDay(1)
    partial, partial_date = pd.Series(dtype=float), None
    if last_date < last_session and month_end in returns.index:
        partial = returns.loc[month_end]
        partial_date = last_date
        returns = returns.drop(index=month_end)
        provenance = provenance.drop(index=month_end)
    returns = returns.loc[:month_end]
    return MarketData(returns, provenance, partial, partial_date, last_date, used)
