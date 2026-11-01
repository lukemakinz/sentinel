# S52 — fade NY cash-open sweep of Asia range

Hash protokołu: `e0c3f48e5bc861187073f80aa33c023ce5bd20fdf0b5ab917741ecd0a33c7de0`.

Zakres Azji 00:00-12:00 UTC, raid w 13:00-16:00 (US cash open), fade po reclaim. Jedno wejście dziennie. Target 1.0R, time-stop 90 min, bez trailing. To nie jest 15-minutowy ORB z S49/S50.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S52_ny_sweep_fade | development | base | 103 | 42.7% | 0.46274153331967044 | $-11.21 | -4.484% | 4.953% |
| S52_ny_sweep_fade | development | stress | 69 | 42.0% | 0.43130349125494877 | $-8.79 | -3.514% | 4.057% |
| S52_ny_sweep_fade | development | severe | 47 | 29.8% | 0.2719596324809322 | $-8.58 | -3.431% | 3.778% |
| S52_ny_sweep_fade | validation | base | 61 | 49.2% | 0.6816421363493559 | $-4.62 | -1.850% | 2.515% |
| S52_ny_sweep_fade | validation | stress | 43 | 53.5% | 0.6761547379888255 | $-2.97 | -1.189% | 1.938% |
| S52_ny_sweep_fade | validation | severe | 27 | 48.1% | 0.6240385315402206 | $-2.18 | -0.873% | 1.447% |

- Decyzja dla `S52_ny_sweep_fade`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 135, 'validation': 84}.
- Udział reżimów 5m: {'UP': 0.299, 'DOWN': 0.284, 'SIDELINE': 0.417}.

| S52_ny_sweep_sideline | development | base | 44 | 38.6% | 0.464792780124972 | $-5.92 | -2.367% | 3.045% |
| S52_ny_sweep_sideline | development | stress | 30 | 36.7% | 0.42711871486592323 | $-4.14 | -1.654% | 2.218% |
| S52_ny_sweep_sideline | development | severe | 20 | 30.0% | 0.28934201120561104 | $-3.80 | -1.520% | 1.826% |
| S52_ny_sweep_sideline | validation | base | 29 | 48.3% | 0.6073931427318254 | $-2.93 | -1.172% | 1.717% |
| S52_ny_sweep_sideline | validation | stress | 18 | 55.6% | 0.7044188160563163 | $-1.18 | -0.472% | 1.095% |
| S52_ny_sweep_sideline | validation | severe | 10 | 40.0% | 0.36061635477512133 | $-1.91 | -0.765% | 1.117% |

- Decyzja dla `S52_ny_sweep_sideline`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 55, 'validation': 35}.
- Udział reżimów 5m: {'UP': 0.299, 'DOWN': 0.284, 'SIDELINE': 0.417}.

Kapitał $250, jeden wspólny rachunek SOL+XRP. Base 5/2 bps, stress 8/5, severe 10/10. Okno ograniczone do cache lokalnego.
