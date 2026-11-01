# Monte Carlo risk-of-ruin dla konta $250

> **SUPERSEDED przez V2 (`run_risk_of_ruin_v2.py`), 2026-09-15.** Metryka
> `median_implied_usd_per_day` poniżej myliła średni przyrost roczny przy
> pełnym reinwestowaniu z realnym oczekiwaniem dziennym od startowych
> $250. Po poprawce (block bootstrap, bez clip() maskującego ruinę,
> osobny test wypłaty $25/dzień) wynik jest jeszcze bardziej
> jednoznaczny: patrz sekcja "V2 — poprawiony wynik" na końcu tego pliku.
> Treść poniżej zachowana dla historii, nie jako aktualna odpowiedź.

Kod: `../../backend/backtest/run_risk_of_ruin_monte_carlo.py`.
Metoda: bootstrap 8000 ścieżek x 250 transakcji (~341 dni przy
historycznym tempie 0,73 tr./dzień) z puli 290 rzeczywistych R-multiple
z S20 H1 (rozwojowe+walidacja+retrospektywa). Sizing: risk_fraction %
BIEŻĄCEGO kapitału na transakcję (compounding).

**Ustalenie o dźwigni:** przy dowolnym testowanym risk_fraction (do 20%)
wymagany margines mieści się dobrze w 5-30x. Dźwignia **nie zmienia
żadnej liczby w tej symulacji** — o wyniku decyduje wyłącznie
risk_fraction i kształt rozkładu wyników transakcji. To nie założenie,
to sprawdzony fakt: dźwignia jest tu wyłącznie narzędziem marginu.

## Scenariusz 1: zero_edge (ta sama wariancja co S20 H1, średnie R=0)

| risk/trade | P(ruina<20%) | P(DD≥30%) | P(DD≥40%) | mediana $end | $/dzień |
|---:|---:|---:|---:|---:|---:|
| 0,5% | 0% | 0% | 0% | $248 | -$0,005 |
| 1% | 0% | 13% | 2% | $244 | -$0,016 |
| 2% | 0% | 72% | 41% | $230 | -$0,060 |
| 3% | 0,9% | 95% | 77% | $208 | -$0,123 |
| 5% | 18% | 100% | 99% | $153 | -$0,284 |

Nawet przy zerowej przewadze, sam sizing generuje **ujemny medianowy
wynik** przez efekt zmienności (Jensen's inequality przy compoundingu).
Sizing nie tworzy przewagi z niczego.

## Scenariusz 2: s20_as_tested (rzeczywisty rozkład, średnie R=-0,04)

| risk/trade | P(ruina<20%) | P(DD≥30%) | P(DD≥40%) | mediana $end | $/dzień |
|---:|---:|---:|---:|---:|---:|
| 0,5% | 0% | 0,1% | 0% | $236 | -$0,040 |
| 1% | 0% | 27% | 5% | $221 | -$0,084 |
| 2% | 0% | 84% | 60% | $188 | -$0,180 |
| 3% | 3,7% | 98% | 88% | $154 | -$0,280 |

Im więcej ryzyka, tym szybciej strategia z lekko ujemną przewagą traci
pieniądze. Potwierdza wprost: zwiększanie stawki nie naprawia ujemnej
expectancy.

## Scenariusz 3: hypothetical_25bp (ilustracyjne, średnie R=+0,25 — **NIE potwierdzona przewaga**, 6x lepsza niż cokolwiek znalezione w tym projekcie)

| risk/trade | P(ruina<20%) | P(DD≥30%) | P(DD≥40%) | mediana $end | mediana $/dzień |
|---:|---:|---:|---:|---:|---:|
| 1% | 0% | 0% | 0% | $456 | $0,60 |
| 2% | 0% | 1,1% | 0% | $800 | $1,61 |
| 3% | 0% | 11,8% | 1,5% | $1 350 | $3,22 |
| 5% | 0% | 67,5% | 24,2% | $3 455 | $9,39 |
| **7,5%** | 0% | **98,1%** | 74,9% | $9 327 | **$26,59** |
| 10% | 0,4% | 100% | 96,8% | $20 786 | $60,15 |

## Odpowiedź na pytanie

Przy **dowolnym potwierdzonym poziomie przewagi znalezionym w tym
projekcie** (co najwyżej ułamki setnych R), sizing nie zbliża wyniku do
$25/dzień na żadnym rozsądnym poziomie ryzyka bankructwa — matematyka
jest zdominowana przez brak edge, nie przez zbyt niskie ryzyko na
transakcję.

Nawet przy **hipotetycznej, niepotwierdzonej przewadze 6x większej**
niż cokolwiek zmierzone (+0,25R), dotarcie do medianowego $25/dzień
wymaga ryzykowania **~7,5% kapitału na transakcję** — co przy P(ruina)
bliskiej zeru oznacza **98% szans na obsunięcie kapitału o 30%+ w ciągu
roku i 75% szans na 40%+**. To nie jest poziom ryzyka spójny z
"dopuszczalnym prawdopodobieństwem utraty konta ≤5%" przy jednoczesnym
ograniczeniu DD do 30-40% — te dwa warunki się tu wykluczają nawet przy
silnej hipotetycznej przewadze.

**Realna granica możliwości $250** przy P(ruina)≤5% i DD celowanym w
30-40%: risk/trade w okolicach 2-3% NAWET przy silnej przewadze daje
$1,6-3,2/dzień (mediana) — rząd wielkości bliżej prawdy niż $25/dzień,
i to przy przewadze, której jeszcze nie mamy.

## Wniosek

$25/dzień z $250 nie jest osiągalne w sposób powtarzalny i kontrolowany
przez ryzyko żadną kombinacją znalezionego (lub prawdopodobnego do
znalezienia w tym samym uniwersum instrumentów) edge i sizingu. Droga
do tego celu wymaga: (a) znacznie większego kapitału startowego przy tym
samym % zwrotu, (b) akceptacji istotnie wyższego ryzyka bankructwa niż
5%, lub (c) fundamentalnie innego źródła przewagi niż cokolwiek
przetestowane w tym projekcie (np. infrastruktura L2/market-making,
poza zakresem retail).

---

## V2 — poprawiony wynik (block bootstrap, bez clip(), dwa osobne pytania)

Kod: `../../backend/backtest/run_risk_of_ruin_v2.py`. Poprawki: block
bootstrap po tygodniach (nie pojedyncze transakcje iid), brak clip()
maskującego bankructwo (ścieżka ginie naprawdę, nie "odbija się" z
mikroskopijnego dodatniego equity), sprawdzenie odległości do
likwidacji przy dźwigni (na podstawie realnych stopów z S20: mediana
0,69%, p90 1,42%, max 3,3% — przy 5x nigdy nie wiąże, przy 30x wiąże dla
0,3% transakcji z najszerszym stopem), oraz P(ruina) opisane jako
"nieobserwowane w N ścieżek", nie jako matematyczne zero.

### A) COMPOUNDING (pełne reinwestowanie, 250 transakcji ≈ rok)

Nawet przy hipotetycznej przewadze +0,25R (6x lepszej niż cokolwiek
zmierzone w tym projekcie): $25/dzień jako **średni roczny przyrost**
wymaga ~7,5-10% ryzyka na transakcję — z 82-98% szansą na obsunięcie
30%+ po drodze.

### B) WYPŁATA $25/dzień (realny test celu — stałe wypłaty, nie compounding)

| Ryzyko/trade | Rzeczywista S20 (mean R=-0,04) | Hipotetyczna +0,25R |
|---:|---:|---:|
| dowolny poziom | **0% przeżywa 30 dni** | **0-1,4% przeżywa 30/90/365 dni** |

**To jest rozstrzygające.** Nawet z hipotetyczną, niepotwierdzoną
przewagą 6x lepszą niż cokolwiek znalezione w 48 przetestowanych
strategiach, stała wypłata $25 dziennie (10% startowego kapitału) z
konta $250 przeżywa choćby 30 dni w mniej niż 1,5% symulowanych ścieżek,
przy DOWOLNYM poziomie ryzyka na transakcję. Wczesna seria strat —
zanim jakikolwiek edge zdąży się uśrednić — niszczy konto, zanim
compounding ma szansę zadziałać.

### Poprawiony wniosek

$25/dzień jako **stała wypłata** z $250 nie jest realistyczne przy
żadnym przetestowanym ani nawet hipotetycznie znacznie lepszym edge —
to matematycznie odrębny, dużo trudniejszy problem niż "$25/dzień
średnio po roku dzięki compoundingowi". Cel w formie "wypłacaj $25
codziennie od dziś" jest z tym kapitałem startowym praktycznie
nieosiągalny w sposób kontrolowany, niezależnie od jakości sygnału czy
dźwigni.
