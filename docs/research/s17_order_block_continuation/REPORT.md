# S17 — Order block retest continuation (base vs OBV+dywergencja)

Hash zamrożonego protokołu: `0c189e02d6cb0073ee7969c386ee71e87a5c1fc2df26f6308b759f737ffc29d8`.

To badanie retrospektywne. BTC nie jest używany — sygnał liczony wyłącznie z ceny handlowanego instrumentu. Maszyneria wyjścia identyczna jak w S16.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| base | development | base | 198 | 43.4% | 0.6620871395004791 | $-14.80 | -5.922% | 6.032% |
| base | development | stress | 144 | 41.7% | 0.42719085542038965 | $-14.90 | -5.962% | 6.045% |
| base | development | severe | 121 | 37.2% | 0.34520250265417735 | $-14.97 | -5.989% | 6.045% |

- Decyzja dla `base`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 351, 'validation': 109, 'retrospective_evaluation': 281}.

| divergence | development | base | 23 | 43.5% | 0.4779979580171264 | $-3.15 | -1.262% | 1.594% |
| divergence | development | stress | 23 | 39.1% | 0.2940052587704663 | $-4.64 | -1.856% | 1.856% |
| divergence | development | severe | 24 | 33.3% | 0.19997398727486076 | $-5.70 | -2.279% | 2.282% |

- Decyzja dla `divergence`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 28, 'validation': 3, 'retrospective_evaluation': 19}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako „najmniej zła”. Divergence (H2) jest ściśle podzbiorem base (H1).

Kapitał: $250; jeden wspólny cash/pending/position; stałe ryzyko $0,50; notional do $125; dźwignia do 5x. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
