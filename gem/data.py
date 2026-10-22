"""Pobieranie notowań ze stooq.pl i budowa miesięcznych stóp zwrotu w PLN.

Surowe pliki CSV trafiają do data/raw/ (pobierane raz, odświeżane flagą
--refresh). Od 2026 r. stooq utrudnia pobieranie skryptom:
- gdy żąda klucza API, skrypt poprosi o niego i zapisze w stooq_apikey.txt
  (albo weźmie go ze zmiennej środowiskowej STOOQ_APIKEY),
- gdy żąda sprawdzenia przeglądarki (JavaScript), skrypt otwiera linki CSV
  w przeglądarce użytkownika i odbiera pliki z folderu Pobrane
  (inny folder: zmienna GEM_DOWNLOADS).
Pliki CSV pobrane ręcznie ze stooq można też wrzucić do data/raw/ pod nazwą
symbolu, np. data/raw/cspx.uk.csv albo data/raw/^tbsp.csv.
"""
import os
import re
import sys
import time
import webbrowser
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
# przybliżeń starszych danych szukamy tylko, gdy lepsze źródło zaczyna się później
TARGET_START = pd.Timestamp("2005-01-31")

_apikey = None
_asked = False
_browser_mode = False
_browser_waits = 0
_run_started = time.time()


def _downloads_dir() -> Path:
    """Folder, do którego przeglądarka zapisuje pobrane pliki."""
    env = os.environ.get("GEM_DOWNLOADS")
    if env:
        return Path(env)
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
                return Path(winreg.QueryValueEx(k, "{374DE290-123F-4565-9164-39C4925E467B}")[0])
        except OSError:
            pass
    return Path.home() / "Downloads"


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


def _is_csv(text: str) -> bool:
    head = text.lstrip("\ufeff").strip()[:200].lower()
    return head.startswith("data,") or head.startswith("date,")


def _is_browser_check(text: str) -> bool:
    t = text[:5000].lower()
    return "verify your browser" in t or "requires javascript" in t


def _downloaded_file(symbol: str, since: float):
    """Plik CSV ze stooq w folderze Pobrane, np. usdpln_d.csv albo cspx_uk_d (1).csv."""
    folder = _downloads_dir()
    if not folder.is_dir():
        return None
    stem = re.escape(symbol.lower().replace(".", "_") + "_d")
    found = [f for f in folder.glob("*.csv")
             if re.fullmatch(stem + r"( ?\(\d+\))?", f.stem.lower()) and f.stat().st_mtime >= since]
    return max(found, key=lambda f: f.stat().st_mtime) if found else None


def _wait_for_download(folder: Path, before: dict, timeout: float):
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1)
        for f in folder.glob("*.csv"):
            try:
                st = f.stat()
            except OSError:
                continue
            if f in before and st.st_mtime <= before[f]:
                continue
            if st.st_size == 0 or Path(str(f) + ".part").exists():
                continue  # pobieranie jeszcze trwa
            time.sleep(0.5)
            if f.stat().st_size != st.st_size:
                continue
            return f
    return None


def _browser_fetch(symbol: str) -> str | None:
    """Pobranie CSV przez przeglądarkę użytkownika (stooq blokuje skrypty)."""
    global _browser_waits
    folder = _downloads_dir()
    # plik mógł zostać pobrany wcześniej (np. ręcznie albo przy poprzednim uruchomieniu)
    ready = _downloaded_file(symbol, _run_started - 12 * 3600)
    if ready is not None:
        print(f"    biorę {ready.name} z {folder}")
        text = ready.read_text(encoding="utf-8", errors="replace")
        return text if _is_csv(text) else ""
    if not folder.is_dir():
        raise StooqError(f"Nie znalazłem folderu pobranych plików {folder}. "
                         "Ustaw zmienną GEM_DOWNLOADS na folder, do którego przeglądarka zapisuje pliki.")
    key = _load_apikey()
    url = STOOQ_URLS[0].format(sym=quote(symbol)) + (f"&apikey={key}" if key else "")
    before = {}
    for f in folder.glob("*.csv"):
        try:
            before[f] = f.stat().st_mtime
        except OSError:
            pass
    for attempt in range(2):
        webbrowser.open_new_tab(url)
        timeout = 60 if _browser_waits == 0 else 30
        _browser_waits += 1
        print(f"    otworzyłem link w przeglądarce, czekam na plik w {folder} (do {timeout} s)")
        f = _wait_for_download(folder, before, timeout)
        if f is None and attempt == 0 and sys.stdin and sys.stdin.isatty():
            print("    Plik się nie pobrał. Zajrzyj do przeglądarki na kartę stooq:\n"
                  "    - jeśli widać weryfikację albo kod z obrazka, przejdź ją,\n"
                  "    - jeśli potem widać link „Pobierz dane w pliku .csv”, kliknij go.")
            answer = input("    Potem naciśnij Enter (albo wpisz p i Enter, żeby pominąć ten symbol): ")
            if answer.strip().lower().startswith("p"):
                return None
            # plik mógł się pobrać, gdy użytkownik klikał w przeglądarce
            f = _wait_for_download(folder, before, 2)
            if f is None:
                continue
        if f is None:
            return None
        text = f.read_text(encoding="utf-8", errors="replace")
        return text if _is_csv(text) else ""
    return None


def fetch(symbol: str, refresh: bool = False) -> pd.Series | None:
    """Dzienne zamknięcia dla symbolu stooq (z cache w data/raw/)."""
    global _browser_mode
    path = _raw_path(symbol)
    if path.exists() and not refresh:
        return _parse_csv(path)
    errors = []
    print(f"  pobieram {symbol}")
    text = None
    for attempt in range(2):
        if _browser_mode:
            break
        key = _load_apikey()
        needs_key = False
        for url in STOOQ_URLS:
            full = url.format(sym=quote(symbol)) + (f"&apikey={key}" if key else "")
            try:
                r = requests.get(full, headers=HEADERS, timeout=30)
            except requests.RequestException as e:
                errors.append(f"{url.split('/')[2]}: {e.__class__.__name__}")
                continue
            body = r.text.strip()
            head = body[:200].lower()
            if r.ok and _is_csv(body):
                text = body
                break
            if "limit" in head and "<" not in head[:1]:
                raise StooqError(f"stooq: przekroczony dzienny limit pobrań ({symbol}). Spróbuj jutro.")
            if _is_browser_check(body):
                _browser_mode = True
                print("    stooq wymaga sprawdzenia przeglądarki, więc dalsze pliki pobiorę przez\n"
                      "    Twoją przeglądarkę. Otworzą się karty stooq i pliki trafią do Pobranych.")
                break
            if head.startswith("<") and "apikey" in body.lower():
                needs_key = True
                break
            snippet = _page_text(body)[:80] if head.startswith("<") else body[:60]
            errors.append(f"{url.split('/')[2]}: HTTP {r.status_code} '{snippet}'")
        if text is not None or not needs_key:
            break
        _ask_apikey("Stooq nie przyjął zapytania bez klucza API." if not key
                    else "Stooq odrzucił zapisany klucz API (wygasł albo jest błędny).")
    if text is None and _browser_mode:
        text = _browser_fetch(symbol)
        if text == "":
            errors.append("stooq nie ma danych dla tego symbolu")
            text = None
        elif text is None:
            errors.append("plik nie pobrał się w przeglądarce")
    if text is not None:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(text.lstrip("\ufeff").strip() + "\n", encoding="utf-8")
        return _parse_csv(path)
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
            if combined is not None and len(combined) and combined.index.min() <= TARGET_START:
                break  # historia jest już wystarczająco długa
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
