# S89 — diagnostyka po odrzuceniu

To rozbicie jest wyłącznie opisowe i zostało wykonane po decyzji
`REJECTED_AT_DEVELOPMENT_GATE`. Nie wolno używać go do przedstawiania
wybranego podzbioru jako wyniku out-of-sample.

## Co zawiodło

- 22 fille: 6 targetów i 16 stopów; win rate 27,3%.
- Średni wynik netto: -0,277R; PF 0,617; PnL -$3,05.
- Long: 11 transakcji, -$2,82, średnio -0,514R.
- Short: 11 transakcji, -$0,23, średnio -0,040R.
- Score 75–85: średnio -0,270R; score 85+: -0,285R. Wyższa ocena nie
  uporządkowała przyszłych rezultatów.
- Dwa, trzy i cztery wcześniejsze dotknięcia nadal miały ujemne średnie R.
  Poziomy z pięcioma i siedmioma dotknięciami przegrały wszystkie, choć próba
  jest za mała do osobnego wniosku statystycznego.
- Re-test do 24h: 9 transakcji i -0,732R średnio; 24–72h: 11 transakcji i
  +0,226R; 72–168h: 2 straty. To obserwacja post hoc, nie nowy filtr.

## Wniosek

Jawny score dobrze opisuje wygląd historycznej strefy, ale w development nie
prognozuje jej dalszej obrony. Liczba wcześniejszych reakcji nie może być
automatycznie traktowana jako „siła”; kolejne testy mogą również zużywać
płynność. Strategia nie przechodzi do validation, paper-forward ani live.
