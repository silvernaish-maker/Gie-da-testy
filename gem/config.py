"""Definicje aktywów, źródeł danych i domyślnych parametrów symulacji GEM.

Każde aktywo ma listę źródeł w kolejności priorytetu: najpierw notowania
samego ETF-u, potem przybliżenia (indeks, rentowność, stopa rynku pieniężnego),
którymi wydłużamy historię wstecz, zanim ETF zadebiutował. Zwroty z przybliżeń
pomniejszamy o roczny koszt (TER) danego ETF-u.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    # "price" – kurs zamknięcia; "yield" – rentowność obligacji w % (syntetyczna
    # obligacja o stałej zapadalności); "rate" – stopa rynku pieniężnego w %
    kind: str
    # kandydaci na symbol w stooq (pierwszy działający wygrywa)
    symbols: tuple
    currency: str = "PLN"
    proxy: bool = False
    # dodatkowy roczny zwrot doliczany do przybliżenia (np. dywidendy dla
    # indeksu cenowego); ujemny oznacza koszt
    extra_annual: float = 0.0
    # zapadalność syntetycznej obligacji (tylko kind="yield")
    maturity: float = 10.0
    label: str = ""


@dataclass(frozen=True)
class Asset:
    key: str
    name: str
    short: str
    ticker: str
    kind: str  # "equity" | "bond"
    currency: str  # waluta, w której fizycznie trzymasz ETF (koszt przewalutowania)
    ter: float
    sources: tuple = field(default_factory=tuple)


ASSETS = {
    "NDX": Asset(
        key="NDX",
        name="Nasdaq-100",
        short="Nasdaq",
        ticker="CNDX (iShares Nasdaq 100, LSE, USD)",
        kind="equity",
        currency="USD",
        ter=0.0030,
        sources=(
            Source("price", ("cndx.uk",), "USD", label="CNDX.UK"),
            Source("price", ("qqq.us",), "USD", proxy=True, label="QQQ.US"),
            Source("price", ("^ndx",), "USD", proxy=True, extra_annual=0.008,
                   label="Nasdaq-100 (indeks cenowy + ~0,8% dyw.)"),
        ),
    ),
    "SPX": Asset(
        key="SPX",
        name="S&P 500",
        short="S&P",
        ticker="CSPX (iShares Core S&P 500, LSE, USD)",
        kind="equity",
        currency="USD",
        ter=0.0007,
        sources=(
            Source("price", ("cspx.uk",), "USD", label="CSPX.UK"),
            Source("price", ("spy.us",), "USD", proxy=True, label="SPY.US"),
            Source("price", ("^spx",), "USD", proxy=True, extra_annual=0.019,
                   label="S&P 500 (indeks cenowy + ~1,9% dyw.)"),
        ),
    ),
    "W20": Asset(
        key="W20",
        name="WIG20TR",
        short="WIG20",
        ticker="ETFBW20TR (Beta ETF WIG20TR, GPW)",
        kind="equity",
        currency="PLN",
        ter=0.0050,
        sources=(
            Source("price", ("etfbw20tr",), label="ETFBW20TR"),
            Source("price", ("wig20tr",), proxy=True, label="indeks WIG20TR"),
            Source("price", ("wig20",), proxy=True, extra_annual=0.035,
                   label="WIG20 (indeks cenowy + ~3,5% dyw.)"),
        ),
    ),
    "M40": Asset(
        key="M40",
        name="mWIG40TR",
        short="mWIG40",
        ticker="ETFBM40TR (Beta ETF mWIG40TR, GPW)",
        kind="equity",
        currency="PLN",
        ter=0.0050,
        sources=(
            Source("price", ("etfbm40tr",), label="ETFBM40TR"),
            Source("price", ("mwig40tr",), proxy=True, label="indeks mWIG40TR"),
            Source("price", ("mwig40",), proxy=True, extra_annual=0.025,
                   label="mWIG40 (indeks cenowy + ~2,5% dyw.)"),
        ),
    ),
    "S80": Asset(
        key="S80",
        name="sWIG80TR",
        short="sWIG80",
        ticker="ETFBS80TR (Beta ETF sWIG80TR, GPW)",
        kind="equity",
        currency="PLN",
        ter=0.0060,
        sources=(
            Source("price", ("etfbs80tr",), label="ETFBS80TR"),
            Source("price", ("swig80tr",), proxy=True, label="indeks sWIG80TR"),
            Source("price", ("swig80",), proxy=True, extra_annual=0.025,
                   label="sWIG80 (indeks cenowy + ~2,5% dyw.)"),
        ),
    ),
    "LONG": Asset(
        key="LONG",
        name="Obligacje długie",
        short="długie",
        ticker="ETFPZULONGDUR (PZU ETF Obligacji Skarbowych Długoterminowych, GPW)",
        kind="bond",
        currency="PLN",
        ter=0.0040,
        sources=(
            Source("price", ("etfpzulongdur",), label="ETFPZULONGDUR"),
            Source("yield", ("10ply.b", "10plpy.b"), proxy=True, maturity=10.0,
                   label="syntetyczna 10-letnia obligacja z rentowności PL 10Y"),
        ),
    ),
    "TBSP": Asset(
        key="TBSP",
        name="Obligacje TBSP",
        short="TBSP",
        ticker="ETFBTBSP (Beta ETF TBSP, GPW)",
        kind="bond",
        currency="PLN",
        ter=0.0047,
        sources=(
            Source("price", ("etfbtbsp",), label="ETFBTBSP"),
            Source("price", ("^tbsp", "tbsp"), proxy=True, label="indeks TBSP"),
        ),
    ),
    "CASH": Asset(
        key="CASH",
        name="Obligacje 6M",
        short="6M",
        ticker="ETFBCASH (Beta ETF Obligacji 6M, GPW)",
        kind="bond",
        currency="PLN",
        ter=0.0030,
        sources=(
            Source("price", ("etfbcash",), label="ETFBCASH"),
            Source("rate", ("plopln6m",), proxy=True,
                   label="naliczanie WIBOR 6M"),
        ),
    ),
}

EQUITIES = [k for k, a in ASSETS.items() if a.kind == "equity"]
BONDS = [k for k, a in ASSETS.items() if a.kind == "bond"]

# kurs do przeliczania aktywów w USD na PLN
FX_SYMBOLS = {"USD": ("usdpln",)}

# Domyślne parametry (zmienialne z linii poleceń)
DEFAULTS = dict(
    lookback=12,             # okno momentum w miesiącach (jak u Antonacciego)
    abs_ref="SPX",           # aktywo testowane w filtrze absolutnym ("SPX" lub "best")
    cash="CASH",             # „bezpieczna” stopa w filtrze absolutnym (odpowiednik T-bills)
    defensive="best_bond",   # "best_bond" albo klucz konkretnej obligacji, np. "LONG"
    commission=0.002,        # prowizja od transakcji (każda strona)
    fx_cost=0.003,           # koszt przewalutowania PLN<->USD (każda konwersja)
    tax_rate=0.19,           # podatek Belki; 0 = IKE/IKZE
)
