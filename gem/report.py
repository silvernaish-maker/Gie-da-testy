"""Raport HTML z wynikami symulacji (samodzielny plik, wykresy w SVG rysowane w JS)."""
import html
import json
import math

PL_MONTHS = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec",
             "sierpień", "wrzesień", "październik", "listopad", "grudzień"]
PL_MONTHS_GEN = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca",
                 "sierpnia", "września", "października", "listopada", "grudnia"]


def esc(s):
    return html.escape(str(s))


def pct(x, digits=1, sign=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    s = f"{abs(x) * 100:.{digits}f}".replace(".", ",")
    if x < 0 and float(s.replace(",", ".")) != 0:
        return f"−{s}%"
    return f"+{s}%" if sign and x > 0 else f"{s}%"


def num(x, digits=2):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    s = f"{abs(x):.{digits}f}".replace(".", ",")
    return f"−{s}" if x < 0 else s


def pln(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x:,.0f} zł".replace(",", " ")


def cls(x):
    return ' class="neg"' if x is not None and not (isinstance(x, float) and math.isnan(x)) and x < 0 else ""


def date_pl(ts, genitive=False):
    months = PL_MONTHS_GEN if genitive else PL_MONTHS
    return f"{months[ts.month - 1]} {ts.year}"


def day_pl(ts):
    return f"{ts.day} {PL_MONTHS_GEN[ts.month - 1]} {ts.year}"


def _table(head, rows, first_col_class="name"):
    out = ['<div class="table-wrap"><table><thead><tr>']
    out += [f"<th>{h}</th>" for h in head]
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>")
        for i, cell in enumerate(row):
            out.append(f'<td class="{first_col_class}">{cell}</td>' if i == 0 else f"<td>{cell}</td>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def summary_table(rows):
    head = ["Portfel", "CAGR (IKE)", "CAGR po Belce*", "Zmienność", "Maks. obsunięcie",
            "Sharpe", "Najgorszy rok", "Najlepszy rok", "Zmiany / rok"]
    body = []
    for r in rows:
        s = r["stats"]
        body.append([
            esc(r["name"]),
            f'<span{cls(s["CAGR"])}>{pct(s["CAGR"])}</span>',
            f'<span{cls(r["cagr_tax"])}>{pct(r["cagr_tax"])}</span>',
            pct(s["Zmienność"]),
            f'<span class="neg">{pct(s["Maks. obsunięcie"])}</span>',
            num(s["Sharpe"]),
            f'<span{cls(s["Najgorszy rok"])}>{pct(s["Najgorszy rok"])}</span>',
            pct(s["Najlepszy rok"]),
            num(r["switches_per_year"], 1) if r["switches_per_year"] is not None else "–",
        ])
    return _table(head, body)


def annual_table(annual):
    head = ["Rok"] + [esc(c) for c in annual["columns"]]
    body = []
    for row in annual["rows"]:
        cells = [esc(row["year"])]
        for v in row["values"]:
            if isinstance(v, str):
                cells.append(f'<span class="held">{esc(v)}</span>')
            else:
                cells.append(f'<span{cls(v)}>{pct(v)}</span>')
        body.append(cells)
    return _table(head, body)


def variants_table(rows):
    head = ["Wariant", "Okno", "Filtr absolutny", "Obrona", "CAGR (IKE)", "CAGR po Belce*",
            "Maks. obsunięcie", "Sharpe", "Zmiany / rok"]
    body = []
    for r in rows:
        name = f"<strong>{esc(r['name'])}</strong>" if r.get("main") else esc(r["name"])
        body.append([
            name, f"{r['lookback']} mies.", esc(r["abs"]), esc(r["def"]),
            f'<span{cls(r["cagr"])}>{pct(r["cagr"])}</span>',
            f'<span{cls(r["cagr_tax"])}>{pct(r["cagr_tax"])}</span>',
            f'<span class="neg">{pct(r["mdd"])}</span>',
            num(r["sharpe"]), num(r["switches_per_year"], 1),
        ])
    return _table(head, body)


def provenance_table(rows):
    head = ["Aktywo", "ETF w portfelu", "Źródło danych (okres)"]
    body = []
    for r in rows:
        segs = "<br>".join(f"{esc(s['label'])} <span class=\"muted\">({esc(s['from'])} – {esc(s['to'])})</span>"
                           for s in r["segments"])
        body.append([esc(r["name"]), f'<span class="mono">{esc(r["ticker"])}</span>', segs])
    return _table(head, body)


def momentum_table(sig, assets):
    head = ["ETF", "Klasa", f"Momentum {sig['lookback']} mies."]
    if sig.get("live_mom"):
        head.append(f"Wstępnie na {esc(sig['live_date'])}")
    body = []
    order = sorted(assets, key=lambda a: (a["kind"] != "equity", -(sig["mom"].get(a["key"]) or -9)))
    for a in order:
        m = sig["mom"].get(a["key"])
        name = esc(a["name"])
        if a["key"] == sig["hold"]:
            name = f"<strong>{name}</strong> <span class=\"chip\">sygnał</span>"
        row = [name, "akcje" if a["kind"] == "equity" else "obligacje", f'<span{cls(m)}>{pct(m)}</span>']
        if sig.get("live_mom"):
            lm = sig["live_mom"].get(a["key"])
            row.append(f'<span{cls(lm)}>{pct(lm)}</span>')
        body.append(row)
    return _table(head, body)


def standalone(page: str) -> str:
    """Pełny dokument HTML do otwarcia z dysku w przeglądarce."""
    return ('<!doctype html>\n<html lang="pl">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '</head>\n<body>\n' + page + '\n</body>\n</html>\n')


def render(ctx) -> str:
    sig = ctx["signal"]
    assets = ctx["assets"]
    by_key = {a["key"]: a for a in assets}
    hold = by_key[sig["hold"]]
    live = ctx.get("live")
    live_html = ""
    if live:
        same = live["hold"] == sig["hold"]
        live_html = (
            f'<p class="lede-note">Wstępny odczyt na {esc(live["date_txt"])} (miesiąc jeszcze trwa): '
            f'<strong>{esc(by_key[live["hold"]]["name"])}</strong>'
            f'{" – bez zmian." if same else " – inny niż ostatni sygnał. Decyzję podejmij po zamknięciu ostatniej sesji miesiąca."}</p>'
        )
    change = ""
    if sig.get("prev_hold") and sig["prev_hold"] != sig["hold"]:
        change = f' Zmiana względem poprzedniego miesiąca (było: {esc(by_key[sig["prev_hold"]]["name"])}).'
    elif sig.get("prev_hold"):
        change = " Bez zmiany względem poprzedniego miesiąca."

    data_json = json.dumps({
        "assets": assets,
        "growth": ctx["growth"],
        "drawdown": ctx["drawdown"],
        "alloc": ctx["alloc"],
        "momentum": {"values": sig["mom"], "hold": sig["hold"], "lookback": sig["lookback"]},
    }, ensure_ascii=False, separators=(",", ":"))

    p = ctx["params"]
    main = ctx["summary"][0]["stats"]
    return TEMPLATE.format(
        title="Symulacja GEM",
        period=f"{esc(main['Od'])} – {esc(main['Do'])}",
        years=num(main["Lata"], 1),
        asof_txt=esc(sig["asof_txt"]),
        hold_name=esc(hold["name"]),
        hold_ticker=esc(hold["ticker"]),
        regime=esc(sig["regime"]),
        change=change,
        live_html=live_html,
        momentum_table=momentum_table(sig, assets),
        summary_table=summary_table(ctx["summary"]),
        annual_table=annual_table(ctx["annual"]),
        variants_table=variants_table(ctx["variants"]),
        provenance_table=provenance_table(ctx["provenance"]),
        switches_html=ctx["switches_html"],
        commission=pct(p["commission"], 2),
        fx_cost=pct(p["fx_cost"], 2),
        tax=pct(p["tax_rate"], 0),
        lookback=p["lookback"],
        generated=esc(ctx["generated"]),
        data_last=esc(ctx["data_last"]),
        data_json=data_json.replace("</", "<\\/"),
    )


TEMPLATE = r"""<title>{title}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
/* Układ: jedna kolumna raportu (maks. ~72rem), najpierw bieżący sygnał, potem wyniki, na końcu założenia. */
:root {{
  --bg: #f5f6f4;
  --surface: #fcfcfb;
  --ink: #121416;
  --ink-2: #4b5056;
  --muted: #7d8287;
  --line: #e1e3df;
  --axis: #c3c6c1;
  --accent: #1c5cab;
  --accent-wash: rgba(28, 92, 171, 0.09);
  --neg: #b42f2f;
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100;
  --s5: #e87ba4; --s6: #008300; --s7: #6250d6; --s8: #e34948;
  --gem: #121416;
  --font-display: "IBM Plex Sans Condensed", "Arial Narrow", system-ui, sans-serif;
  --font-body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #0e0f10; --surface: #17191a; --ink: #eeefec; --ink-2: #c2c4bd; --muted: #8b8e89;
    --line: #2a2c2b; --axis: #3a3d3b; --accent: #6da7ec; --accent-wash: rgba(109, 167, 236, 0.14);
    --neg: #ef7b7b;
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
    --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767;
    --gem: #eeefec;
    color-scheme: dark;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #0e0f10; --surface: #17191a; --ink: #eeefec; --ink-2: #c2c4bd; --muted: #8b8e89;
  --line: #2a2c2b; --axis: #3a3d3b; --accent: #6da7ec; --accent-wash: rgba(109, 167, 236, 0.14);
  --neg: #ef7b7b;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
  --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767;
  --gem: #eeefec;
  color-scheme: dark;
}}
* {{ box-sizing: border-box; }}
body {{
  background: var(--bg); color: var(--ink); font-family: var(--font-body);
  font-size: 15px; line-height: 1.55; margin: 0;
}}
.page {{
  max-width: 72rem; margin: 0 auto;
  padding-left: max(16px, env(safe-area-inset-left, 0px));
  padding-right: max(16px, env(safe-area-inset-right, 0px));
  padding-block: 28px 56px;
  display: flex; flex-direction: column; gap: 40px;
}}
h1, h2, h3 {{ font-family: var(--font-display); text-wrap: balance; margin: 0; line-height: 1.15; }}
h1 {{ font-size: 2rem; font-weight: 600; }}
h2 {{ font-size: 1.45rem; font-weight: 600; }}
h3 {{ font-size: 1.05rem; font-weight: 600; }}
p {{ margin: 0; max-width: 68ch; }}
.eyebrow {{ font-size: 0.75rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); font-weight: 600; }}
.muted {{ color: var(--muted); }}
.mono {{ font-family: var(--font-mono); font-size: 0.85em; }}
.neg {{ color: var(--neg); }}
header {{ display: flex; flex-direction: column; gap: 8px; }}
header p {{ color: var(--ink-2); }}
section {{ display: flex; flex-direction: column; gap: 14px; min-width: 0; }}
.section-head {{ display: flex; flex-direction: column; gap: 4px; }}
.section-head p {{ color: var(--ink-2); }}

.signal {{
  display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 28px;
  background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 24px;
}}
.signal-main {{ display: flex; flex-direction: column; gap: 10px; min-width: 0; }}
.signal-asset {{ font-family: var(--font-display); font-size: 3rem; font-weight: 600; line-height: 1; letter-spacing: -0.01em; }}
.signal-ticker {{ font-family: var(--font-mono); font-size: 0.85rem; color: var(--ink-2); }}
.regime {{ display: inline-flex; align-self: flex-start; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px;
  background: var(--accent-wash); color: var(--accent); font-weight: 600; font-size: 0.8rem; }}
.lede-note {{ color: var(--ink-2); font-size: 0.9rem; }}
.chip {{ display: inline-block; padding: 0 7px; border-radius: 999px; background: var(--accent-wash); color: var(--accent);
  font-size: 0.7rem; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; vertical-align: 1px; }}

.card {{ background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 18px 18px 12px; min-width: 0; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 0.82rem; color: var(--ink-2); margin-bottom: 8px; }}
.legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
.legend i {{ display: inline-block; width: 14px; height: 3px; border-radius: 2px; }}
.legend i.sq {{ width: 10px; height: 10px; border-radius: 2px; }}
.chart {{ position: relative; width: 100%; }}
.chart svg {{ display: block; width: 100%; height: auto; overflow: visible; }}
.chart text {{ font-family: var(--font-body); font-size: 11px; fill: var(--muted); }}
.tip {{
  position: absolute; pointer-events: none; z-index: 2; min-width: 150px;
  background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.12); padding: 8px 10px; font-size: 0.8rem; color: var(--ink);
  font-variant-numeric: tabular-nums;
}}
.tip b {{ display: block; margin-bottom: 4px; font-weight: 600; }}
.tip div {{ display: flex; justify-content: space-between; gap: 14px; }}
.tip i {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }}

.table-wrap {{ overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 10px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.86rem; font-variant-numeric: tabular-nums; }}
th, td {{ padding: 8px 12px; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--line); }}
td.name {{ white-space: normal; min-width: 8.5rem; }}
td .held {{ display: inline-block; min-width: 9rem; white-space: normal; text-align: left; }}
th {{ font-weight: 600; color: var(--ink-2); font-size: 0.78rem; background: var(--surface); position: sticky; top: 0; }}
td.name, th:first-child {{ text-align: left; }}
tbody tr:last-child td {{ border-bottom: 0; }}
tbody tr:hover td {{ background: var(--accent-wash); }}
.held {{ color: var(--ink-2); font-size: 0.8rem; }}
.grid-2 {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }}
.notes {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); gap: 16px; }}
.notes > div {{ display: flex; flex-direction: column; gap: 6px; }}
.notes p, .notes li {{ color: var(--ink-2); font-size: 0.9rem; }}
.notes ul {{ margin: 0; padding-left: 1.1rem; display: flex; flex-direction: column; gap: 4px; }}
footer {{ color: var(--muted); font-size: 0.8rem; display: flex; flex-direction: column; gap: 4px; }}
@media (max-width: 760px) {{
  .signal, .grid-2 {{ grid-template-columns: minmax(0, 1fr); }}
  .signal-asset {{ font-size: 2.4rem; }}
  h1 {{ font-size: 1.6rem; }}
}}
</style>

<div class="page">
  <header>
    <span class="eyebrow">Global Equity Momentum · ETF-y dla inwestora z PLN</span>
    <h1>Symulacja strategii GEM</h1>
    <p>Rotacja co miesiąc między Nasdaq-100, S&amp;P 500, WIG20TR, mWIG40TR i sWIG80TR, z ucieczką do polskich obligacji skarbowych, gdy rynek akcji traci impet. Reguły według opisu GEM na inwestomat.eu, okres {period} ({years} lat), wyniki w złotych.</p>
  </header>

  <section aria-labelledby="h-signal">
    <div class="signal">
      <div class="signal-main">
        <span class="eyebrow" id="h-signal">Sygnał na koniec {asof_txt}</span>
        <span class="signal-asset">{hold_name}</span>
        <span class="signal-ticker">{hold_ticker}</span>
        <span class="regime">Tryb: {regime}</span>
        <p class="lede-note">Ten ETF trzymasz przez cały następny miesiąc.{change}</p>
        {live_html}
      </div>
      <div>
        <div class="chart" id="chart-momentum" role="img" aria-label="Momentum {lookback}-miesięczne wszystkich ETF-ów"></div>
      </div>
    </div>
    {momentum_table}
  </section>

  <section aria-labelledby="h-growth">
    <div class="section-head">
      <h2 id="h-growth">Wartość 100 000 zł</h2>
      <p>Skala logarytmiczna, rachunek bez podatku (IKE/IKZE), po prowizjach, kosztach przewalutowania i opłatach ETF-ów.</p>
    </div>
    <div class="card">
      <div class="legend" id="legend-growth"></div>
      <div class="chart" id="chart-growth" role="img" aria-label="Wartość portfela GEM na tle strategii kup i trzymaj"></div>
    </div>
  </section>

  <section aria-labelledby="h-alloc">
    <div class="section-head">
      <h2 id="h-alloc">Gdzie był portfel</h2>
      <p>Każdy pasek to okres trzymania jednego ETF-u. Najedź lub dotknij, żeby zobaczyć daty i wynik.</p>
    </div>
    <div class="card">
      <div class="legend" id="legend-alloc"></div>
      <div class="chart" id="chart-alloc" role="img" aria-label="Oś czasu pozycji strategii GEM"></div>
    </div>
  </section>

  <section aria-labelledby="h-dd">
    <div class="section-head">
      <h2 id="h-dd">Obsunięcia kapitału</h2>
      <p>Spadek od poprzedniego szczytu, miesięcznie.</p>
    </div>
    <div class="card">
      <div class="legend" id="legend-dd"></div>
      <div class="chart" id="chart-dd" role="img" aria-label="Obsunięcia GEM i S&amp;P 500"></div>
    </div>
  </section>

  <section aria-labelledby="h-summary">
    <div class="section-head">
      <h2 id="h-summary">Wyniki na tle „kup i trzymaj”</h2>
      <p>Ten sam okres dla wszystkich. CAGR po Belce to wynik na zwykłym rachunku: podatek 19% płacony co roku od zrealizowanych zysków, z odliczaniem strat przez 5 lat, plus podatek przy sprzedaży na końcu okresu.</p>
    </div>
    {summary_table}
  </section>

  <section aria-labelledby="h-annual">
    <div class="section-head">
      <h2 id="h-annual">Wyniki roczne</h2>
      <p>Rachunek bez podatku. Kolumna „Pozycje” pokazuje, w czym GEM był w danym roku.</p>
    </div>
    {annual_table}
  </section>

  <section aria-labelledby="h-variants">
    <div class="section-head">
      <h2 id="h-variants">Warianty reguł</h2>
      <p>Jak zmienia się wynik, gdy zmienić jedno ustawienie. Duże różnice między sąsiednimi wariantami oznaczają, że wynik zależy od szczęścia w doborze parametrów.</p>
    </div>
    {variants_table}
  </section>

  <section aria-labelledby="h-switches">
    <div class="section-head">
      <h2 id="h-switches">Ostatnie zmiany pozycji</h2>
    </div>
    {switches_html}
  </section>

  <section aria-labelledby="h-rules">
    <div class="section-head"><h2 id="h-rules">Reguły i założenia</h2></div>
    <div class="notes">
      <div>
        <h3>Reguła miesięczna</h3>
        <ul>
          <li>Na zamknięciu ostatniej sesji miesiąca liczysz stopę zwrotu z {lookback} miesięcy dla każdego ETF-u (w PLN).</li>
          <li>Filtr absolutny: jeśli S&amp;P 500 zarobił więcej niż ETFBCASH (polski odpowiednik bonów skarbowych), zostajesz w akcjach.</li>
          <li>Filtr względny: kupujesz ETF akcyjny z najwyższym momentum.</li>
          <li>W przeciwnym razie kupujesz ETF obligacyjny z najwyższym momentum (długie, TBSP albo krótkie).</li>
        </ul>
      </div>
      <div>
        <h3>Koszty</h3>
        <ul>
          <li>Prowizja {commission} od każdej transakcji.</li>
          <li>Przewalutowanie PLN↔USD {fx_cost} przy przejściu między ETF-em z GPW a ETF-em z Londynu.</li>
          <li>Opłaty roczne ETF-ów (TER) są w notowaniach; dla okresów sprzed debiutu odejmowane od indeksu.</li>
          <li>Podatek Belki {tax} na zwykłym rachunku; IKE/IKZE bez podatku.</li>
        </ul>
      </div>
      <div>
        <h3>Ograniczenia</h3>
        <ul>
          <li>Zanim ETF-y zadebiutowały, ich rolę grają indeksy i syntetyczne obligacje (tabela niżej), więc wcześniejsze lata to przybliżenie.</li>
          <li>Sygnał i transakcja na tym samym zamknięciu; w praktyce kupisz dzień później, po innej cenie.</li>
          <li>Wyniki historyczne nie gwarantują przyszłych. To symulacja, nie rekomendacja inwestycyjna.</li>
        </ul>
      </div>
    </div>
    {provenance_table}
  </section>

  <footer>
    <span>Dane: stooq.pl, ostatnie notowanie {data_last}. Raport wygenerowany {generated}.</span>
    <span>* CAGR po Belce: wartość po sprzedaży całej pozycji na koniec okresu i zapłacie podatku.</span>
  </footer>
</div>

<script id="gem-data" type="application/json">{data_json}</script>
<script>
(function () {{
  const D = JSON.parse(document.getElementById("gem-data").textContent);
  const NS = "http://www.w3.org/2000/svg";
  const assets = Object.fromEntries(D.assets.map(a => [a.key, a]));
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const color = key => key === "GEM" ? css("--gem") : css("--s" + assets[key].slot);
  const fmtPct = (v, d = 1) => (v < 0 ? "−" : "") + Math.abs(v * 100).toFixed(d).replace(".", ",") + "%";
  const fmtPln = v => Math.round(v).toLocaleString("pl-PL") + " zł";
  const MONTHS = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];
  const fmtDate = s => {{ const [y, m] = s.split("-"); return MONTHS[+m - 1] + " " + y; }};

  function el(tag, attrs, parent) {{
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }}
  function legend(id, keys, label, square) {{
    const box = document.getElementById(id);
    box.innerHTML = "";
    keys.forEach(k => {{
      const s = document.createElement("span");
      const i = document.createElement("i");
      if (square) i.className = "sq";
      i.style.background = color(k);
      s.appendChild(i);
      s.appendChild(document.createTextNode(label(k)));
      box.appendChild(s);
    }});
  }}
  function tipBox(host) {{
    let t = host.querySelector(".tip");
    if (!t) {{ t = document.createElement("div"); t.className = "tip"; t.hidden = true; host.appendChild(t); }}
    return t;
  }}
  function placeTip(host, tip, x, y) {{
    const w = host.clientWidth, tw = tip.offsetWidth;
    tip.style.left = Math.max(0, Math.min(w - tw, x + 14 > w - tw ? x - tw - 14 : x + 14)) + "px";
    tip.style.top = Math.max(0, y - 10) + "px";
  }}
  function yearTicks(dates, plotW) {{
    const years = [...new Set(dates.map(d => d.slice(0, 4)))];
    const step = Math.max(1, Math.ceil(years.length / Math.max(2, Math.floor(plotW / 60))));
    const out = [];
    dates.forEach((d, i) => {{
      const y = +d.slice(0, 4);
      if (d.slice(5, 7) === "01" && y % step === 0) out.push([i, String(y)]);
    }});
    return out;
  }}

  function lineChart(host, cfg) {{
    const W = Math.max(300, host.clientWidth), H = cfg.height || Math.round(Math.min(420, Math.max(240, W * 0.45)));
    host.querySelectorAll("svg").forEach(s => s.remove());
    const m = {{ l: 58, r: 12, t: 10, b: 26 }};
    const pw = W - m.l - m.r, ph = H - m.t - m.b, n = cfg.dates.length;
    const svg = el("svg", {{ viewBox: `0 0 ${{W}} ${{H}}`, width: W, height: H }});
    host.prepend(svg);
    const all = cfg.series.flatMap(s => s.values.filter(v => v != null));
    let lo = Math.min(...all), hi = Math.max(...all);
    const tf = cfg.log ? Math.log : v => v;
    if (!cfg.log) {{ lo = Math.min(lo, 0); hi = Math.max(hi, 0); }}
    const pad = (tf(hi) - tf(lo)) * 0.04 || 1;
    const y0 = tf(lo) - (cfg.log ? pad : 0), y1 = tf(hi) + pad;
    const X = i => m.l + (n === 1 ? 0 : i / (n - 1) * pw);
    const Y = v => m.t + ph - (tf(v) - y0) / (y1 - y0) * ph;
    const g = el("g", {{}}, svg);
    // siatka i oś Y
    let ticks = [];
    if (cfg.log) {{
      for (let e = Math.floor(Math.log10(lo)) - 1; e <= Math.ceil(Math.log10(hi)) + 1; e++)
        for (const f of [1, 2, 5]) {{ const v = f * Math.pow(10, e); if (tf(v) >= y0 && tf(v) <= y1) ticks.push(v); }}
      if (ticks.length > 7) ticks = ticks.filter(v => /^[15]/.test(String(v)));
    }} else {{
      const span = hi - lo, raw = span / 5, p10 = Math.pow(10, Math.floor(Math.log10(raw)));
      const st = [1, 2, 2.5, 5, 10].map(k => k * p10).find(k => k >= raw);
      for (let v = Math.ceil(lo / st) * st; v <= hi + 1e-9; v += st) ticks.push(+v.toFixed(10));
    }}
    ticks.forEach(v => {{
      el("line", {{ x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: css("--line"), "stroke-width": 1 }}, g);
      const t = el("text", {{ x: m.l - 8, y: Y(v) + 4, "text-anchor": "end" }}, g);
      t.textContent = cfg.yFmt(v);
    }});
    if (!cfg.log) el("line", {{ x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), stroke: css("--axis"), "stroke-width": 1 }}, g);
    el("line", {{ x1: m.l, x2: W - m.r, y1: m.t + ph, y2: m.t + ph, stroke: css("--axis"), "stroke-width": 1 }}, g);
    yearTicks(cfg.dates, pw).forEach(([i, lab]) => {{
      const t = el("text", {{ x: X(i), y: H - 8, "text-anchor": "middle" }}, g);
      t.textContent = lab;
    }});
    // serie (najważniejsza rysowana na końcu, na wierzchu)
    [...cfg.series].reverse().forEach(s => {{
      const pts = s.values.map((v, i) => v == null ? null : [X(i), Y(v)]);
      let d = "", pen = false;
      pts.forEach(p => {{ if (!p) {{ pen = false; return; }} d += (pen ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1); pen = true; }});
      if (cfg.area) {{
        const first = pts.findIndex(p => p), last = pts.length - 1 - [...pts].reverse().findIndex(p => p);
        el("path", {{ d: d + `L${{X(last)}},${{Y(0)}}L${{X(first)}},${{Y(0)}}Z`, fill: color(s.key), "fill-opacity": 0.1, stroke: "none" }}, g);
      }}
      el("path", {{ d, fill: "none", stroke: color(s.key), "stroke-width": s.key === "GEM" ? 2.5 : 2,
        "stroke-linejoin": "round", "stroke-linecap": "round" }}, g);
    }});
    // warstwa interakcji
    const tip = tipBox(host);
    const cross = el("line", {{ y1: m.t, y2: m.t + ph, stroke: css("--axis"), "stroke-width": 1, visibility: "hidden" }}, svg);
    const dots = cfg.series.map(s => el("circle", {{ r: 4, fill: color(s.key), stroke: css("--surface"), "stroke-width": 2, visibility: "hidden" }}, svg));
    const hit = el("rect", {{ x: m.l, y: m.t, width: pw, height: ph, fill: "transparent" }}, svg);
    const move = ev => {{
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * W / r.width;
      const i = Math.max(0, Math.min(n - 1, Math.round((px - m.l) / pw * (n - 1))));
      cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("visibility", "visible");
      let rows = "";
      cfg.series.forEach((s, k) => {{
        const v = s.values[i];
        if (v == null) {{ dots[k].setAttribute("visibility", "hidden"); return; }}
        dots[k].setAttribute("cx", X(i)); dots[k].setAttribute("cy", Y(v)); dots[k].setAttribute("visibility", "visible");
        rows += `<div><span><i style="background:${{color(s.key)}}"></i>${{s.label}}</span><span>${{cfg.tipFmt(v)}}</span></div>`;
      }});
      tip.innerHTML = `<b>${{fmtDate(cfg.dates[i])}}</b>` + rows;
      tip.hidden = false;
      placeTip(host, tip, X(i) * r.width / W, (ev.clientY - r.top));
    }};
    const leave = () => {{ tip.hidden = true; cross.setAttribute("visibility", "hidden"); dots.forEach(d => d.setAttribute("visibility", "hidden")); }};
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", leave);
  }}

  function momentumChart(host) {{
    host.querySelectorAll("svg").forEach(s => s.remove());
    const vals = Object.entries(D.momentum.values).filter(([k, v]) => v != null);
    vals.sort((a, b) => (assets[a[0]].kind === assets[b[0]].kind ? b[1] - a[1] : assets[a[0]].kind === "equity" ? -1 : 1));
    const ctx2d = document.createElement("canvas").getContext("2d");
    ctx2d.font = "600 11px " + css("--font-body");
    const labW = Math.max(...vals.map(([k]) => ctx2d.measureText(assets[k].name).width));
    const W = Math.max(280, host.clientWidth), row = 30, m = {{ l: Math.ceil(labW) + 14, r: 52, t: 6, b: 6 }};
    const H = m.t + m.b + row * vals.length + 10;
    const svg = el("svg", {{ viewBox: `0 0 ${{W}} ${{H}}`, width: W, height: H }});
    host.prepend(svg);
    const lo = Math.min(0, ...vals.map(v => v[1])), hi = Math.max(0, ...vals.map(v => v[1]));
    // miejsce na wartość po lewej stronie ujemnych słupków
    const padL = lo < 0 ? 46 : 0, pw = W - m.l - m.r - padL;
    const X = v => m.l + padL + (v - lo) / ((hi - lo) || 1) * pw;
    let y = m.t;
    vals.forEach(([k, v], idx) => {{
      if (idx > 0 && assets[k].kind !== assets[vals[idx - 1][0]].kind) y += 10;
      const x0 = X(0), x1 = X(v), bh = 18, by = y + (row - bh) / 2;
      const left = Math.min(x0, x1), w = Math.max(1, Math.abs(x1 - x0));
      const r = Math.min(4, w / 2);
      // zaokrąglony tylko koniec z wartością, prosty przy osi zera
      const d = v >= 0
        ? `M${{left}},${{by}}H${{left + w - r}}Q${{left + w}},${{by}} ${{left + w}},${{by + r}}V${{by + bh - r}}Q${{left + w}},${{by + bh}} ${{left + w - r}},${{by + bh}}H${{left}}Z`
        : `M${{left + w}},${{by}}H${{left + r}}Q${{left}},${{by}} ${{left}},${{by + r}}V${{by + bh - r}}Q${{left}},${{by + bh}} ${{left + r}},${{by + bh}}H${{left + w}}Z`;
      el("path", {{ d, fill: color(k), "fill-opacity": k === D.momentum.hold ? 1 : 0.55 }}, svg);
      const lab = el("text", {{ x: m.l - 10, y: y + row / 2 + 4, "text-anchor": "end" }}, svg);
      lab.textContent = assets[k].name;
      lab.style.fill = k === D.momentum.hold ? css("--ink") : css("--ink-2");
      if (k === D.momentum.hold) lab.style.fontWeight = 600;
      const val = el("text", {{ x: v >= 0 ? x1 + 6 : x1 - 6, y: y + row / 2 + 4, "text-anchor": v >= 0 ? "start" : "end" }}, svg);
      val.textContent = fmtPct(v);
      val.style.fill = css("--ink-2");
      y += row;
    }});
    el("line", {{ x1: X(0), x2: X(0), y1: m.t, y2: y, stroke: css("--axis"), "stroke-width": 1 }}, svg);
  }}

  function allocChart(host) {{
    host.querySelectorAll("svg").forEach(s => s.remove());
    const runs = D.alloc, n = runs.reduce((s, r) => s + r.months, 0);
    const W = Math.max(300, host.clientWidth), H = 62, m = {{ l: 4, r: 4, t: 6, b: 22 }};
    const pw = W - m.l - m.r, bh = H - m.t - m.b;
    const svg = el("svg", {{ viewBox: `0 0 ${{W}} ${{H}}`, width: W, height: H }});
    host.prepend(svg);
    const tip = tipBox(host);
    let i = 0;
    const dates = [];
    runs.forEach(r => {{
      const x = m.l + i / n * pw, w = r.months / n * pw;
      const rect = el("rect", {{ x: x + 1, y: m.t, width: Math.max(0.5, w - 2), height: bh, rx: 2, fill: color(r.hold) }}, svg);
      const show = ev => {{
        tip.innerHTML = `<b>${{assets[r.hold].name}}</b><div><span>Od</span><span>${{fmtDate(r.from)}}</span></div>`
          + `<div><span>Do</span><span>${{fmtDate(r.to)}}</span></div><div><span>Miesięcy</span><span>${{r.months}}</span></div>`
          + `<div><span>Wynik</span><span>${{fmtPct(r.ret)}}</span></div>`;
        tip.hidden = false;
        const b = svg.getBoundingClientRect();
        placeTip(host, tip, ev.clientX - b.left, 0);
      }};
      rect.addEventListener("pointermove", show);
      rect.addEventListener("pointerdown", show);
      rect.addEventListener("pointerleave", () => {{ tip.hidden = true; }});
      for (let k = 0; k < r.months; k++) dates.push(r.from);
      i += r.months;
    }});
    const startYear = +runs[0].from.slice(0, 4), endYear = +runs[runs.length - 1].to.slice(0, 4);
    const span = endYear - startYear + 1, step = Math.max(1, Math.ceil(span / Math.max(2, Math.floor(pw / 60))));
    const [y0, m0] = runs[0].from.split("-").map(Number);
    for (let yr = startYear + 1; yr <= endYear; yr++) {{
      if (yr % step) continue;
      const idx = (yr - y0) * 12 - (m0 - 1);
      if (idx <= 0 || idx >= n) continue;
      const t = el("text", {{ x: m.l + idx / n * pw, y: H - 6, "text-anchor": "middle" }}, svg);
      t.textContent = yr;
    }}
  }}

  function draw() {{
    const gk = D.growth.series.map(s => s.key);
    legend("legend-growth", gk, k => D.growth.series.find(s => s.key === k).label);
    lineChart(document.getElementById("chart-growth"), {{
      dates: D.growth.dates, series: D.growth.series, log: true,
      yFmt: v => v >= 1e6 ? (v / 1e6).toLocaleString("pl-PL") + " mln" : (v / 1e3).toLocaleString("pl-PL") + " tys.",
      tipFmt: fmtPln,
    }});
    const dk = D.drawdown.series.map(s => s.key);
    legend("legend-dd", dk, k => D.drawdown.series.find(s => s.key === k).label);
    lineChart(document.getElementById("chart-dd"), {{
      dates: D.drawdown.dates, series: D.drawdown.series, area: true, height: 240,
      yFmt: v => fmtPct(v, 0), tipFmt: v => fmtPct(v),
    }});
    const held = [...new Set(D.alloc.map(r => r.hold))];
    legend("legend-alloc", D.assets.map(a => a.key).filter(k => held.includes(k)), k => assets[k].name, true);
    allocChart(document.getElementById("chart-alloc"));
    momentumChart(document.getElementById("chart-momentum"));
  }}
  draw();
  let last = window.innerWidth;
  window.addEventListener("resize", () => {{ if (Math.abs(window.innerWidth - last) > 20) {{ last = window.innerWidth; draw(); }} }});
  if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
  new MutationObserver(draw).observe(document.documentElement, {{ attributes: true, attributeFilter: ["data-theme"] }});
}})();
</script>
"""
