# S87 — Strong Level Retest

Jedna strategia, nie router wielu strategii. Szuka wyłącznie pierwszego powrotu
do mocnej strefy będącej przecięciem causalnego order blocku i wielokrotnie
bronionego poziomu wsparcia/oporu.

## Co oznacza „mocny poziom”

- order block musi poprzedzać impuls, który wybija wcześniej potwierdzony swing;
- przy cenie strefy muszą istnieć co najmniej dwa wcześniejsze, potwierdzone
  pivoty tego samego typu (dołki dla longa, szczyty dla shorta);
- impuls musi mieć co najmniej 1,2 ATR przemieszczenia i 1,2x mediany wolumenu;
- strefa otrzymuje jawny wynik 0–100: struktura 25, displacement 20, wolumen 15,
  konfluencja S/R 20, trend 10, geometria 5, świeżość 5;
- handlujemy wyłącznie wynik co najmniej 70/100.

## Wejście i ryzyko

Limit na 50% strefy jest uzbrajany przy zamknięciu świecy potwierdzającej, więc
czeka już przed pierwszym re-testem. Ważność: 72 godziny. Stop leży 0,20 ATR za
strefą. Cel to najbliższy causalny poziom przeciwny, jeśli daje 2–3R, w innym
wypadku 3R. Jeżeli do przeszkody nie ma 2R, setup jest odrzucany.

Portfel ma jeden pending i najwyżej jedną pozycję, ryzyko 0,20% kapitału na
trade, notional do 1x equity i maksymalną dźwignię 5x. Wynik musi przejść koszty
base, stress i severe oraz osobne okno validation. Dopiero potem może wejść do
paper-forward; nie jest dopuszczony do live.
