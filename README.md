# Symulacja GEM dla polskiego inwestora

Backtest strategii **GEM (Global Equity Momentum)** Gary'ego Antonacciego w wersji
opisanej na [inwestomat.eu/strategia-gem](https://inwestomat.eu/strategia-gem/),
zbudowanej z ETF-ów dostępnych dla inwestora z Polski. Wszystkie wyniki są liczone w PLN.

## Aktywa

| Rola | ETF | Dane przed debiutem ETF-u |
|---|---|---|
| Akcje USA – Nasdaq-100 | CNDX (iShares, LSE, USD, bez hedgingu) | QQQ.US, potem indeks Nasdaq-100 |
| Akcje USA – S&P 500 | CSPX (iShares, LSE, USD, bez hedgingu) | SPY.US, potem indeks S&P 500 |
| Akcje GPW – duże spółki | ETFBW20TR (Beta ETF WIG20TR) | indeks WIG20TR |
| Akcje GPW – średnie spółki | ETFBM40TR (Beta ETF mWIG40TR) | indeks mWIG40TR |
| Akcje GPW – małe spółki | ETFBS80TR (Beta ETF sWIG80TR) | indeks sWIG80TR |
| Obligacje długie (~10 lat) | ETFPZULONGDUR (PZU, od 08.2026) | syntetyczna 10-letnia obligacja z rentowności PL 10Y |
| Obligacje średnie | ETFBTBSP (Beta ETF TBSP) | indeks TBSP |
| Obligacje krótkie (6M) | ETFBCASH (Beta ETF Obligacji 6M) | naliczanie WIBOR 6M |

Na GPW nie ma ETF-ów dokładnie na obligacje 10-, 3- i 1-letnie, więc ich rolę pełnią
trzy obligacyjne ETF-y o różnym czasie trwania: długie (PZU), średnie (TBSP) i krótkie (6M).
ETF-y USA są niezabezpieczone walutowo, więc wynik zawiera zmiany kursu USD/PLN.

Zwroty z indeksów i syntetycznych obligacji użytych przed debiutem ETF-u są pomniejszane
o roczną opłatę (TER) danego ETF-u. Dokładne źródło każdego miesiąca jest w raporcie
(tabela „Reguły i założenia”).

## Reguły (domyślne)

Na zamknięciu ostatniej sesji każdego miesiąca:

1. Liczysz stopę zwrotu z 12 miesięcy (w PLN) dla wszystkich ETF-ów.
2. **Momentum absolutne:** jeśli S&P 500 zarobił więcej niż ETFBCASH (polski odpowiednik
   amerykańskich bonów skarbowych), zostajesz w akcjach.
3. **Momentum względne:** kupujesz ETF akcyjny z najwyższym 12-miesięcznym wynikiem
   (Nasdaq-100, S&P 500, WIG20TR, mWIG40TR, sWIG80TR).
4. W przeciwnym razie kupujesz ETF obligacyjny z najwyższym 12-miesięcznym wynikiem.
5. Cały portfel jest zawsze w jednym ETF-ie.

Raport pokazuje też warianty: filtr absolutny na najlepszym indeksie zamiast S&P 500,
stała obligacja w obronie, okna 3/6/9 miesięcy, tylko USA, tylko GPW, bez kosztów.

## Koszty i podatki

- prowizja 0,20% od każdej transakcji (`--commission`),
- przewalutowanie PLN↔USD 0,30% przy przejściu między ETF-em z GPW i z Londynu (`--fx-cost`),
- podatek Belki 19% (`--tax`): saldo zysków i strat liczone co rok, strata odliczana
  przez 5 lat, podatek płacony ze sprzedaży części pozycji. Wyniki pokazane są
  osobno dla IKE/IKZE (bez podatku) i zwykłego rachunku.

## Uruchomienie

```bash
pip install -r requirements.txt
python run_gem.py              # pobiera dane ze stooq.pl, zapisuje raport
python run_gem.py --refresh    # odświeża notowania
python run_gem.py --lookback 6 --defensive LONG --abs-ref best
python -m pytest -q            # testy logiki na sztucznych danych
```

Wyniki:

- `reports/gem_raport.html` – raport z bieżącym sygnałem, wykresami i tabelami,
- `reports/gem_sygnaly.csv` – decyzja i momentum każdego ETF-u na koniec każdego miesiąca.

### Dane

Notowania pobierane są ze [stooq.pl](https://stooq.pl) i zapisywane w `data/raw/`
(ten katalog nie trafia do repozytorium). Jeśli pobieranie nie działa (limit dzienny,
brak dostępu do sieci), pobierz plik CSV ręcznie ze stooq („Dane historyczne” →
„Pobierz dane w pliku .csv”, interwał dzienny) i zapisz go jako
`data/raw/<symbol>.csv`. Symbole: `usdpln`, `cndx.uk`, `qqq.us`, `^ndx`, `cspx.uk`, `spy.us`,
`^spx`, `etfbw20tr`, `wig20tr`, `etfbm40tr`, `mwig40tr`, `etfbs80tr`, `swig80tr`,
`etfpzulongdur`, `10ply.b`, `etfbtbsp`, `^tbsp`, `etfbcash`, `plopln6m`.

## Ograniczenia

- Przed debiutem ETF-ów wyniki pochodzą z indeksów i obligacji syntetycznych, więc są
  przybliżeniem.
- Sygnał i transakcja są liczone na tym samym zamknięciu; w praktyce kupisz dzień później.
- Wyniki historyczne nie gwarantują przyszłych. To symulacja, nie rekomendacja inwestycyjna.
