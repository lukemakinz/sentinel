# S7 — trend-only VP reclaim (finalny test dyscyplinujący)

Protokół zablokowany przed policzeniem holdout: [`protocol.json`](protocol.json),
wybór wariantu przed holdout: [`selection.json`](selection.json).

## Zasady, których nie rozmiękczono

- Obowiązkowy trend 4h (`bias4h == side`) dla każdego wejścia, bez wyjątku na
  "silny sygnał odwrócenia". Poprzednia wersja miała taką furtkę i nie przeżyła
  holdout — tutaj jest usunięta, nie dostrojona.
- Jedna reguła wejścia: reclaim VAL/VAH zgodny z trendem. Bez zliczania punktów
  z RSI/EMA-cross/MACD/dywergencji jako dodatkowych głosów.
- Brak celu liczby transakcji dziennie — częstotliwość to wynik obserwowany,
  nie kryterium doboru wariantu.
- Reguła stop ustalona z góry: jeśli żaden wariant nie osiągnie profit factor >1
  po kosztach na holdout dla co najmniej 3 z 4 par, kierunek badawczy
  indicator/price-action scalping S7 zostaje zamknięty. Bez kolejnej rundy
  nowych wskaźników po zobaczeniu holdout.

## Dane i okna

Train: 2025-08-01 – 2026-02-01. Validation: luty–kwiecień 2026. Holdout:
kwiecień–lipiec 2026 (miesiąc po miesiącu) — okres nigdy wcześniej nieużywany
do wyboru parametrów w żadnej wcześniejszej rundzie S7.

## Wybór przed holdout

Wybrany wariant: `S7vp_trend_5m_market_goal10` (jedyny z `positive_both: true`
na train i validation, spośród 7 wariantów: 5m/15m × market/limit × cel
zysku/RR). Wyniki rozwojowe, portfel 4 par:

| Faza | Transakcje | Wynik | PF |
|---|---:|---:|---:|
| Train | 100 | +0,02% | 1,01 |
| Validation | 73 | +0,04% | 1,02 |

Te liczby są w praktyce szumem statystycznym (PF≈1,01–1,02 przy 73–100
transakcjach na cały portfel), nie sygnałem. Wybrano ten wariant tylko dlatego,
że był jedynym nieujemnym na obu etapach — to była najlepsza dostępna opcja,
nie mocna kandydatura.

## Holdout, scenariusz 20x (bez stresu poślizgu)

| Miesiąc | Para | Transakcje | Wynik netto | PF | Maks. obsunięcie |
|---|---|---:|---:|---:|---:|
| Kwiecień 2026 | BTCUSDT | 0 | 0,00% | — | 0,00% |
| Kwiecień 2026 | ETHUSDT | 0 | 0,00% | — | 0,00% |
| Kwiecień 2026 | SOLUSDT | 0 | 0,00% | — | 0,00% |
| Kwiecień 2026 | BNBUSDT | 0 | 0,00% | — | 0,00% |
| Maj 2026 | BTCUSDT | 0 | 0,00% | — | 0,00% |
| Maj 2026 | ETHUSDT | 0 | 0,00% | — | 0,00% |
| Maj 2026 | SOLUSDT | 0 | 0,00% | — | 0,00% |
| Maj 2026 | BNBUSDT | 2 | −0,03% | 0,83 | 0,26% |
| Czerwiec 2026 | BTCUSDT | 0 | 0,00% | — | 0,00% |
| Czerwiec 2026 | ETHUSDT | 10 | +0,13% | 1,19 | 0,65% |
| Czerwiec 2026 | SOLUSDT | 16 | −1,00% | 0,39 | 1,15% |
| Czerwiec 2026 | BNBUSDT | 0 | 0,00% | — | 0,00% |
| Lipiec 2026 | BTCUSDT | 0 | 0,00% | — | 0,00% |
| Lipiec 2026 | ETHUSDT | 0 | 0,00% | — | 0,00% |
| Lipiec 2026 | SOLUSDT | 0 | 0,00% | — | 0,00% |
| Lipiec 2026 | BNBUSDT | 0 | 0,00% | — | 0,00% |

BTCUSDT nie zawarł ani jednej transakcji w żadnym z 4 miesięcy holdout przy
20x (0 wejść na 4×30 dni). Portfel łącznie: kwiecień 0,00%, maj −0,01%,
czerwiec −0,22%, lipiec 0,00%. Wyniki na 30x i w scenariuszu stresowego
poślizgu (osobne pliki `holdout_summary.json`/`holdout_portfolio.json`) są
w tym samym rzędzie wielkości lub gorsze — więcej wejść na SOL przy wyższej
dźwigni (do 21/miesiąc), ale z PF 0,37–0,77 i wyraźnie ujemnym wynikiem.

## Dlaczego nie przeszło

Reguła "wejście tylko zgodnie z trendem 4h" i reguła "reclaim VAL/VAH" w dużej
mierze się wykluczają: reclaim to z definicji zachowanie zakresu/odwrócenia
(cena wychodzi poza wartość i wraca), a filtr trendu tłumi większość takich
sytuacji, bo w silnym trendzie ceny rzadko wracają do VAL/VAH pod prąd, a gdy
wracają zgodnie z trendem, jest to już spóźnione wejście blisko POC. To
strukturalny konflikt reguł, nie tylko kwestia rzadkości próby — tam, gdzie
sygnały jednak przeszły filtr kosztowy i weszły w pozycję (SOL, czerwiec),
wynik był wyraźnie ujemny, a nie tylko rzadki.

## Werdykt

**Reguła stop się spełniła: żadna para nie utrzymuje PF>1 na sensownej próbie
w holdout, więc warunek "PF>1 dla ≥3 z 4 par" nie jest spełniony.** Zgodnie z
ustalonym z góry protokołem, kierunek badawczy indicator/price-action
scalping S7 (Volume Profile + RSI/EMA/CVD/dywergencje + liquidity sweep +
ICT FVG + trend-only reclaim) zostaje zamknięty. Nie szukamy kolejnej
kombinacji wskaźników w tym samym schemacie.

Nic nie zostało włączone do skanera live ani egzekutora. Kod i dane zostają
w repozytorium jako udokumentowany, zamknięty eksperyment badawczy.
