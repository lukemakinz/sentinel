# S17b — Order block: świeca odrzucenia zamiast pierwszego dotknięcia

Hash zamrożonego protokołu: `3c9784c8d50ed19af58ffb42f43777bc1a941ad197a2bad3c1dcea4d30edfe5b`.

To badanie retrospektywne. Jedyna zmiana względem S17: trigger wymaga świecy odrzucenia zamiast samego dotknięcia strefy. Reżim/struktura/flow/egzekucja identyczne jak w S17.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| base | development | base | 162 | 46.3% | 0.4743396833579664 | $-14.80 | -5.921% | 6.032% |
| base | development | stress | 126 | 42.9% | 0.3204386225019328 | $-14.91 | -5.963% | 6.046% |
| base | development | severe | 110 | 36.4% | 0.27400201287878273 | $-14.86 | -5.945% | 6.002% |

- Decyzja dla `base`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 301, 'validation': 101, 'retrospective_evaluation': 246}.

| divergence | development | base | 19 | 42.1% | 0.4061692116933167 | $-2.94 | -1.175% | 1.704% |
| divergence | development | stress | 19 | 36.8% | 0.23266517640657014 | $-4.29 | -1.715% | 1.790% |
| divergence | development | severe | 19 | 31.6% | 0.16206523383765015 | $-4.73 | -1.894% | 1.894% |

- Decyzja dla `divergence`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 20, 'validation': 2, 'retrospective_evaluation': 13}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako „najmniej zła”.

Kapitał: $250; jeden wspólny cash/pending/position; stałe ryzyko $0,50; notional do $125; dźwignia do 5x. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
