# Raport końcowy projektu — poszukiwanie edge na $250 kapitału

Data: 2026-09-15. Zakres: wszystkie rodziny strategii przetestowane w
tym projekcie (backtesty historyczne, metodologia frozen-protocol:
development → validation → retrospective_evaluation, koszty base/
stress/severe, dokładnie 2 hipotezy na protokół, bez grid searchu).

## Tabela zbiorcza

| Rodzina | Kod/protokoły | Najlepszy PF OOS | PF stress | Transakcje | Max DD | $/dzień | Powód odrzucenia |
|---|---|---:|---:|---:|---:|---:|---|
| Order block + reżim + OBV (kontynuacja trendu) | S16-S19, S21-S28, S37 | ~0,6-1,1 | <1,0 | — | — | — | Za mało/PF<1 na bramce rozwojowej w większości wariantów |
| **Order block + OI (najlepiej zbadana linia)** | S18/S20/S22-S28 | 1,12 (walidacja S20 H1) | 0,86 | 137+43 | 4,5% | ~$0,01/dzień (base) | Stress PF<1,00 na walidacji |
| **+ filtr sesji (S43)** | S43 | **1,48 (walidacja)** | **1,04** | 75+30 | — | — | **Jedyna, która przeszła obie formalne bramki** — ale retrospektywa PF 0,68/0,38, załamanie |
| + poprawka kierunku OI (S44A) | S44A | 1,00 | 0,66-0,74 | 123-121 | — | — | Rejected przy development (poprawka neutralna/gorsza) |
| + dynamiczny filtr płynności (S44C) | S44C | 0,95 (walidacja) | 0,78 | 80+34 | — | — | Rejected na walidacji; diagnostyka pokazała odwrócenie separacji między oknami |
| + reżim BTC TREND/CHOP/SHOCK (S45) | S45 | — | — | — | — | — | Znak efektu niestabilny między oknami dla każdego reżimu |
| **+ weto funding<0 (S46)** | S46 | 1,50 (walidacja) | **1,05** | 117+25+89 | 4,24% | **+$0,0045 base / -$0,051 stress** | Diagnostyka (β=-0,593R, p=0,002) potwierdzona statystycznie, ale pełny system: retro PF 0,83/0,40. **REJECTED AS TRADING STRATEGY** |
| Funding carry | S11, S31-36 | dodatni, mały | — | — | — | ułamki centa/dzień | Realny, ale finansowo nieistotny w tej skali |
| ML classifier (HistGradientBoosting) | S29 | — | — | — | — | — | Brak przewagi OOS |
| AI adjudicator (gpt-4o-mini) | S30 | 1,23 (dev, n=51) | — | — | — | — | Nie replikuje na walidacji (WR 25%, exp. -0,375R, n=8) |
| Liquidation cascade fade | S38 | 0,45-0,55 | — | 103/59 | — | — | Rejected na bramce rozwojowej, wyraźna strata |
| Liquidation cascade continuation | S39 | 1,03 (78 fill) | 0,80 | 78/51 | — | — | Rejected — PF<1,05 mimo bliskości progu |
| Cross-sectional momentum | XSM-28 | — | — | — | — | — | Rejected na bramce rozwojowej |
| 4H ekstremalne wyprzedanie/wykupienie | S40 (pilot) / S41 (rozszerzone) | 4,56 (pilot, n=14) → **0,58** (n=82, rozszerzone) | — | 14→82 | — | — | Klasyczna regresja do średniej — mała próba myliła |
| Pary relative-value (ALT/BTC) | S42 | 0,74-0,52 | — | 93-82 | — | — | Rejected na bramce rozwojowej |
| Breakout/momentum 1-5m (discovery) | D1-D4 | 0,24-0,72 | — | 107-228 | 6% | — | Wszystkie 4 warianty jednoznacznie ujemne na każdym symbolu |
| **Mikrostruktura order-flow (aggTrades)** | M1 | — | — | — | — | — | Efekt REALNY i stabilny co do znaku (89,5% dni dodatnich @3s), ale ~100-250x za mały względem kosztu round-trip (0,11-0,14 bps vs 14-26 bps) |

## Co udowodnił ten projekt

**Nie udowodnił:** że nie istnieje żaden pojedynczy dzień, w którym $250
mogłoby zarobić $25. Taki dzień jest zawsze statystycznie możliwy przy
wystarczającej zmienności.

**Udowodnił:** że w bardzo szerokim, uczciwie przetestowanym zestawie
mechanizmów — kontynuacja trendu, mean-reversion, breakout, momentum
wymuszonego przepływu, funding/carry, cross-sectional, relative value,
ML, AI oraz mikrostruktura order-flow — nie znaleziono niczego, co
dawałoby podstawy oczekiwać **powtarzalnego** $25/dzień (10% kapitału
dziennie) z $250. Jeden realny, dobrze potwierdzony statystycznie efekt
(imbalance przepływu zleceń) istnieje, ale jest o 2-3 rzędy wielkości za
mały względem kosztów wykonania dla handlu kierunkowego na poziomie
retail.

**Nieprzetestowane, świadomie poza zakresem:** pełne L2 (top-5/10 book),
market-making/pasywne wypełnienia, pozycja w kolejce, cross-venue
arbitraż, fee/rebate edge. Mogą mieć przewagę rzędu ułamków bp, ale
wymagają infrastruktury (niskie opóźnienia, kolokacja, dobra pozycja w
kolejce) nieadekwatnej do celu "$250 → agresywny trading retailowy".

## Zmiana pytania badawczego

Zamiast: *"jak zrobić $25/dzień z $250?"*

Teraz: *"jaki maksymalny rozsądny zwrot daje się uzyskać z $250 przy
określonym dopuszczalnym prawdopodobieństwie utraty konta?"*

Patrz `RISK_OF_RUIN_MONTE_CARLO.md` w tym samym katalogu za pełną
odpowiedź liczbową.
