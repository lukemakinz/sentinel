# S44A — poprawka kierunku OI: założenia i uczciwy wynik

Kod: `../../../backend/l1_filter/order_block_oi_fixed_scalp.py` (pełny w
sekcji poniżej). Protokół formalny: `protocol.json` w tym katalogu.
Strategia bazowa (przed poprawką): `../s20_ob_oi_patient_runner/`.

## Status

**Odrzucona na bramce rozwojowej.** Poprawka była merytorycznie słuszna
(patrz niżej), ale empirycznie nie odsłoniła ukrytej przewagi — wynik
wylądował dokładnie na granicy opłacalności, gorzej lub tak samo jak
strategia bazowa S20 H1.

## Skąd się wzięła ta wersja

Zewnętrzny przegląd strategii S43 wykrył asymetrię w filtrze Open
Interest, obecną od S18 i odziedziczoną przez większość strategii w tym
projekcie (S18→S43): warunek wymagał rosnącego OI dla longów, ale
**malejącego** OI dla shortów. Według klasycznej analizy kwadrantu
cena/OI:

- cena↑ + OI↑ = nowy kapitał w longi = zdrowa kontynuacja
- cena↑ + OI↓ = shorty się zamykają (short squeeze) = słabsze
- cena↓ + OI↑ = nowy kapitał w shorty = zdrowa kontynuacja
- cena↓ + OI↓ = longi się likwidują = słabsze (nie nowa podaż)

Oryginalny kod wybierał dla shortów czwarty kwadrant (cena↓+OI↓) —
dokładnie ten "słabszy" przypadek, sprzeczny z własnym uzasadnieniem
strategii ("zdrowa kontynuacja, nie wyciskanie, które się kończy").
S44A poprawia to: OI musi rosnąć dla **obu** kierunków, nic więcej się
nie zmienia.

## Rynki i kapitał (identyczne jak S20)

- Pary: ETHUSDT, SOLUSDT, BNBUSDT
- Kapitał startowy: $250, jedna wspólna pozycja globalnie
- Dźwignia: do 5x, limit nominalny: $125, limit depozytu: $25
- Ryzyko na transakcję: stałe $0,50 (0,2% kapitału)

## Mechanizm wejścia (identyczny jak S20 H1/H2, jedna linia zmieniona)

1. Order block: świeca z displacementem ≥1,5x ATR i wolumenem ≥1,2x
   średniej, potwierdzona 3 świece później, jedna szansa na strefę
   (pierwsze dotknięcie w ciągu 32 świec 15-minutowych).
2. Reżim: trend 4h (EMA200+nachylenie) potwierdzony ADX≥20 na 1h.
3. Przepływ: OBV powyżej/poniżej swojej EMA9.
4. **Open Interest (POPRAWIONE):** musi rosnąć w ciągu ostatnich 2h —
   identyczny warunek dla longa i shorta (wcześniej: rosnąć dla longa,
   maleć dla shorta).

## Zarządzanie pozycją — dwie testowane wersje (kopie S20 H1/H2)

| | partial (breakeven+trailing od) | trailing (chandelier) | twardy limit |
|---|---:|---:|---:|
| H1 patient | +1,5R | 2,5x ATR | +8R |
| H2 very_patient | +2,0R | 3,0x ATR | +10R |

## Okna czasowe i koszty — identyczne jak S20/S43

- Rozwojowe: 2025-08-01 – 2026-02-01, walidacyjne: 2026-02-01 – 2026-04-01,
  retrospektywne: 2026-04-01 – 2026-09-01
- Koszty bazowe/stress/severe: 2/5/2/2, 5/8/5/5, 10/10/10/10 bps

## Wynik (okno rozwojowe, kapitał $250)

| Wariant | PF base | PF stress | PF severe | Transakcje | Wynik $ (base) |
|---|---:|---:|---:|---:|---:|
| S44A patient | 1,005 | 0,664 | 0,384 | 123 | +$0,13 |
| S44A very_patient | 0,995 | 0,740 | 0,500 | 121 | -$0,15 |
| *(dla porównania: S20 H1 oryginalny)* | *1,066* | *0,764* | *0,437* | *137* | *+$2,08* |

Obie wersje **odrzucone na bramce rozwojowej** (wymagany PF >1,05) — nie
doszły nawet do walidacji.

## Wniosek

Poprawka dotyczyła wyłącznie strony short (longi bez zmian) — inny zestaw
krótkich transakcji przeszedł filtr, ale zbiorczo wynik nie poprawił się,
a nawet nieznacznie się pogorszył względem oryginału. To nie unieważnia
rozumowania o kwadrancie cena/OI jako takiego — ale pokazuje, że w tych
konkretnych danych (ETH/SOL/BNB, ten okres) nie był to czynnik
ograniczający wynik S20. Kod pozostaje poprawiony (bo teraz zgadza się
z własnym uzasadnieniem strategii), ale jako ulepszenie strategii — ślepy
zaułek.

## Znane ograniczenia

- Test zmienia wyłącznie jedną linię logiki (kierunek OI dla shortów);
  wszystko inne identyczne z S20 H1/H2.
- Nie testuje wariantu z progiem procentowym/z-score OI (to osobny,
  jeszcze nieprzetestowany krok, gdyby ktoś chciał go wykonać osobno).
- Diagnostyka retrospektywna na danych historycznych — nie wynik z
  prawdziwego handlu.
