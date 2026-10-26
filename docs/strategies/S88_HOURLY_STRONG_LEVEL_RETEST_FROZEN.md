# S88 — Hourly Strong Level Retest

To następca, a nie równoległa strategia wobec S87. Logika pozostaje jedna:
order block musi pokrywać się z mocnym wsparciem/oporem, a limit ma oczekiwać
na pierwszy przyszły powrót ceny. Zmienia się wyłącznie rozdzielczość strefy z
4h na 1h, ponieważ S87 dała tylko jeden fill w development i nie była możliwa
do statystycznej oceny.

Poziom otrzymuje 0–100 punktów za wybicie struktury, displacement, wolumen,
liczbę wcześniejszych pivotów przy tej samej cenie, zgodność trendu, geometrię
i świeżość. Minimum to 70 i co najmniej dwa wcześniejsze dotknięcia S/R.

Limit: 50% strefy od chwili potwierdzenia, ważny 36h. Stop: 0,20 ATR poza
strefą. Cel: najbliższy przeciwny swing dający co najmniej 2R, maksymalnie 3R;
bez miejsca na 2R nie ma transakcji. Jedna pozycja globalnie, ryzyko 0,20%,
notional do 1x equity, lewar do 5x. Kandydat wymaga przejścia zamrożonych bramek
development, kosztów stress i niezależnego validation przed paper-forward.
