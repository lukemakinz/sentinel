# S89 — Broad Strong Level Retest

To jedna strategia stosowana na ośmiu płynnych kontraktach, nie osiem różnych
strategii. Każdy rynek może mieć własne oczekujące zlecenie na wcześniej
potwierdzonym poziomie, ale konto może utrzymywać najwyżej jedną otwartą
pozycję. Pierwszy dotknięty limit wygrywa; pierwszy re-test zużywa strefę.

Definicja mocnego poziomu pozostaje bez zmian względem S88: causalny 1h order
block, wybicie już potwierdzonej struktury, minimum dwa wcześniejsze pivoty S/R
przy tej samej cenie, displacement 1,5 ATR, wolumen 1,25x i wynik minimum
70/100. Limit leży na środku strefy i może czekać siedem dni. Stop jest 0,20
ATR za strefą, a target wymaga co najmniej 2R i ma cap 3R.

Ryzyko to 0,20% kapitału, notional maksymalnie 1x equity, dźwignia do 5x,
dzienny stop 1%, tygodniowy 1,8%. Bramka development wymaga co najmniej 20
fili oraz odporności na koszty stress. Dopiero niezależne validation może
zezwolić na paper-forward; live pozostaje wyłączone.
