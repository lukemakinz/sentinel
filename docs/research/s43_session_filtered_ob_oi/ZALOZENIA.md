# S43 — order block + OI + filtr sesji: założenia i uczciwy wynik

Kod: `strategy_s43.py` w tym samym katalogu (samodzielny plik). Pełny,
formalny protokół (JSON, z hashem zamrożonym przed wynikiem): `protocol.json`.
Bazowa wersja bez filtru sesji: `../s20_ob_oi_patient_runner/`.

## Status

**Nie zatwierdzona do prawdziwego kapitału.** Najdalej zaszła strategia
z 47 przetestowanych w tym projekcie (przeszła obie formalne bramki), ale
przewaga załamała się w najświeższym, jeszcze nieoglądanym oknie danych.
Szczegóły w sekcji "Wynik" poniżej.

## Rynki i kapitał

- Pary: ETHUSDT, SOLUSDT, BNBUSDT (kontrakty perpetual futures, Binance)
- Kapitał startowy: $250
- Jedna wspólna pozycja globalnie (nie handlujemy wszystkich trzech par naraz)
- Dźwignia: do 5x, limit nominalny pozycji: $125, limit depozytu: $25
- Ryzyko na transakcję: stałe $0,50 (0,2% kapitału)
- Dzienny stop strat: $1,50; tygodniowy: $4,50

## Mechanizm wejścia (wszystkie warunki muszą być spełnione naraz)

1. **Order block** — świeca 15-minutowa z ruchem (displacement) ≥1,5x ATR
   i wolumenem ≥1,2x średniej 20-świecowej, potwierdzona 3 świece później.
   Strefa (zakres open-close tej świecy) jest "aktywna" przez 32 świece
   (~8h) i daje dokładnie jedną szansę wejścia — pierwsze dotknięcie
   (retest), potem strefa jest usuwana niezależnie od wyniku.
2. **Reżim rynku** — trend na interwale 4h (cena powyżej/poniżej EMA200
   z odpowiednim nachyleniem) potwierdzony siłą trendu ADX≥20 na 1h.
   Wchodzimy tylko zgodnie z trendem wyższego interwału (kontynuacja,
   nie łapanie dołków/szczytów).
3. **Przepływ (OBV)** — wskaźnik On-Balance Volume musi wspierać kierunek
   (być powyżej/poniżej swojej 9-okresowej EMA) w momencie retestu.
4. **Open Interest** — musi rosnąć (long) lub spadać (short) w ciągu
   ostatnich 2h. To odróżnia "nowe pozycje wchodzą za ruchem" od
   "ruch to tylko wyciskanie krótkich/długich pozycji, które się kończy".
   Dane z publicznego, darmowego archiwum Binance (bez klucza API).
5. **Filtr sesji (jedyny nowy element względem bazowej wersji S20)** —
   sygnał liczy się tylko jeśli świeca zamyka się między 07:00 a 20:00
   UTC (Londyn + Nowy Jork). Godziny azjatyckie/nocne są pomijane.

## Zarządzanie pozycją (identyczne jak bazowa wersja S20 H1)

- Stop początkowy: tuż za strefą order block (+0,15x ATR bufora)
- Przy +1,5R: stop przesuwa się na breakeven, aktywuje się trailing
- Trailing: chandelier stop 2,5x ATR od ekstremum ceny
- Twardy limit zysku: +8R
- Maksymalny czas trzymania pozycji: 4h, potem wymuszone zamknięcie

## Koszty transakcyjne (trzy scenariusze testowane równolegle)

| | maker | taker | poślizg | penetracja limitu |
|---|---:|---:|---:|---:|
| bazowy | 2bps | 5bps | 2bps | 2bps |
| stress | 5bps | 8bps | 5bps | 5bps |
| severe | 10bps | 10bps | 10bps | 10bps |

## Okna czasowe testu

- Rozwojowe: 2025-08-01 do 2026-02-01 (184 dni)
- Walidacyjne: 2026-02-01 do 2026-04-01 (59 dni)
- Retrospektywne (dane najświeższe, oglądane jako ostatnie): 2026-04-01 do 2026-09-01 (153 dni)

## Wynik (kapitał $250, bez zmian sizingu)

| Okno | PF base | PF stress | Transakcje | Wynik $ (base) | Wynik $ (stress) |
|---|---:|---:|---:|---:|---:|
| rozwojowe | 1,39 | 0,82 | 75 | +$6,62 | -$3,47 |
| **walidacyjne** | **1,48** | **1,04** | 30 | +$2,57 | +$0,23 |
| retrospektywne | **0,68** | **0,38** | 62 | **-$4,65** | **-$9,79** |
| **razem (13 mies.)** | — | — | 167 | **+$4,54** | **-$13,03** |

**Bramka walidacyjna przeszła w całości** (pierwszy i jedyny raz w tym
projekcie): PF bazowy >1,10 ✓, PF stress ≥1,00 ✓, ≥20 transakcji ✓,
≥2 zyskowne pary ✓, żadna para nie zdominowała wyniku ✓.

**Ale okno retrospektywne (dane, których strategia "nie widziała" w
momencie budowy) pokazuje załamanie przewagi.** To nie jest formalnie
wymagana bramka promocyjna (do tego trzeba forward paper tradingu na
prawdziwie nowych danych), ale jest to najbardziej wiarygodny dostępny
test — i wynik jest negatywny.

## Wniosek

$250 → $254,54 w 13 miesięcy w najlepszym uczciwym scenariuszu
(~$0,01/dzień), albo $250 → $237 pod kosztami stress. Nie $25/dzień.
Przewaga wygląda na realną w części okresu, ale krychą i zanikającą —
dokładnie ten sam wzorzec regresji do średniej widziany już dwa razy
wcześniej w tym projekcie (S24→S28, S30). Jedyny sposób, żeby to
rozstrzygnąć ostatecznie: forward paper trading na nowych danych, nie
kolejny backtest na historii.

## Znane ograniczenia (przeniesione z protokołu)

- Filtr sesji zmniejsza próbkę względem bazowego S20 H1 (137→75
  transakcji rozwojowych) — mniej danych, szerszy margines błędu.
- To filtr, nie nowy sygnał: jeśli przechodzi bramki, leżąca u podstaw
  przewaga jest wciąż tą samą kruchą przewagą co w S20 H1, tylko na
  mniejszej, ograniczonej do sesji próbce.
- Godziny sesji to standardowe granice kalendarzowe UTC, nie prawdziwy
  pomiar płynności/spreadu z księgi zleceń (tego projekt nigdzie nie
  rekonstruuje).
- To diagnostyka retrospektywna na danych historycznych — nie wynik
  z prawdziwego, aktywnego handlu.
