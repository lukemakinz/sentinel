# S35 — niezależny audyt jakości sygnału

Ten audyt nie zmienia zamrożonego protokołu, wyniku ani decyzji promocyjnej.
Oba setupy są przyczynowe: percentyle używają wyłącznie 180 wcześniejszych
fundingów, z wyłączeniem klasyfikowanego zdarzenia. Funding z 2 marca miał
surowy timestamp `08:00:00.001` i został przyczynowo przesunięty do `08:05`,
więc najwcześniejsze wejście o `08:10` nie zawiera look-ahead.

| Cecha | 28.02.2024 | 02.03.2024 |
|---|---:|---:|
| Funding / próg | 6,016 / 5,000 bp = 1,203x | 8,773 / 5,358 bp = 1,637x |
| Percentyl fundingu | 98,90% | 100,00% |
| Return 60m / Q80 | 0,724% / 0,709% = 1,021x | 3,473% / 0,744% = 4,668x |
| Percentyl return | 81,22% | 98,90% |
| Premium / minimum | 8,637 / 3 bp = 2,879x | 13,806 / 3 bp = 4,602x |
| Kompresja | 30,22%, margines +5,22 pp | 32,75%, margines +7,75 pp |
| Reversal | -0,200% = 0,298 ATR | -1,078% = 0,919 ATR |

## Kandydat z 28 lutego

Funding był naprawdę ekstremalny, lecz ruch 60m przeszedł próg tylko o 2,12%,
a reversal był wyłącznie zmianą znaku o 0,298 ATR. Świeca potwierdzająca
zamknęła się 40% od minimum swojego zakresu i nie przebiła minimum świecy
pre-funding. Nie wystąpił potwierdzony bearish market-structure shift.

Po wejściu short premium natychmiast rozszerzył się z 6,03 do 8,21 i 12,23 bp.
Przed stopem maksymalny ruch korzystny wyniósł tylko 0,171R; stop został
trafiony o 16:20 UTC, a wynik stress wyniósł -0,4997 USD / -1R. Do 17:00 cena
wzrosła około 21,3% względem wejścia. Setup próbował złapać szczyt trwającego
wybicia na podstawie zbyt słabego potwierdzenia.

## Kandydat z 2 marca

Drugi kandydat był dużo silniejszy statystycznie, lecz również nie przebił
minimum świecy pre-funding. Ukończone momentum nadal było skrajnie wzrostowe:

- 4h: +4,63%, percentyl 97,79%;
- 12h: +6,93%, percentyl 95,58%;
- 24h: +23,45%, percentyl 98,90%.

Blokada minimum nominału nie ukryła zysku. Diagnostyczne pominięcie minimum 20
USD kończy się stopem: -0,4779 USD base i -0,4959 USD / -1R stress przy
nominale 19,21 USD. Zwiększenie ilości do 137 DOGE, aby wymusić nominał ponad
20 USD, podniosłoby ryzyko do około 0,519 USD, o 3,93% ponad limit. Po stopie
cena później spadła, lecz najlepszy ruch w 180 minut osiągnął 1,76R i nie
dotknął targetu 2R.

## Wniosek i nowe hipotezy

Podstawowym problemem była jakość i synchronizacja wejścia, nie kosztowy
break-even, target 2R ani sam stop 1R. Rzadki setup nie był przez to pewnym
setupem. Potencjalne ulepszenia są na razie wyłącznie hipotezami post-hoc:

- short dopiero po zamknięciu poniżej minimum świecy pre-funding;
- minimalny reversal displacement względem ATR, zamiast samej zmiany znaku;
- druga pełna świeca musi potwierdzić brak ponownego rozszerzania premium;
- veto, gdy ukończone 4h i 24h momentum w stronę fundingu jest nadal skrajne;
- dla shorta zamknięcie świecy potwierdzającej blisko minimum jej zakresu.

Nie wolno promować ani stroić tych filtrów na dwóch opisanych przypadkach.
Muszą utworzyć nowy zamrożony protokół i zostać ocenione na niezależnej próbie.
S35 pozostaje `EDGE_FAIL`.
