# S54 — fade alt residual versus BTC

Hash protokołu: `bbe9c4a79754c076f960bb1c0b93c07c0394a86f4f8907b1bcab26f9472882d2`.

SOL/XRP vs BTC, z-score 1h residual na 48h oknie. Fade przy |z|>=2. BTC tylko jako lead, nie handlowany. Target 1.0R, time-stop 90 min, bez trailing. Jedna próba na kubeł 4h.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S54_residual_fade | development | base | 181 | 45.3% | 0.5396185501281697 | $-14.23 | -5.691% | 6.013% |
| S54_residual_fade | development | stress | 145 | 40.0% | 0.4280805068318422 | $-14.87 | -5.949% | 5.977% |
| S54_residual_fade | development | severe | 78 | 39.7% | 0.3934361010912047 | $-10.15 | -4.060% | 4.060% |
| S54_residual_fade | validation | base | 120 | 38.3% | 0.3741133212610823 | $-14.78 | -5.914% | 6.030% |
| S54_residual_fade | validation | stress | 99 | 36.4% | 0.3134047070938282 | $-13.49 | -5.397% | 5.499% |
| S54_residual_fade | validation | severe | 56 | 37.5% | 0.31662600306039357 | $-9.40 | -3.761% | 3.783% |

- Decyzja dla `S54_residual_fade`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 259, 'validation': 183}.
- Udział reżimów 15m: {'UP': 0.299, 'DOWN': 0.284, 'SIDELINE': 0.417}.

| S54_residual_fade_sideline | development | base | 90 | 36.7% | 0.31075260475857425 | $-13.06 | -5.225% | 5.263% |
| S54_residual_fade_sideline | development | stress | 65 | 35.4% | 0.27278610877758575 | $-10.90 | -4.362% | 4.372% |
| S54_residual_fade_sideline | development | severe | 33 | 24.2% | 0.16860901045254548 | $-7.20 | -2.881% | 3.065% |
| S54_residual_fade_sideline | validation | base | 65 | 38.5% | 0.3802827722964001 | $-10.78 | -4.310% | 4.374% |
| S54_residual_fade_sideline | validation | stress | 35 | 34.3% | 0.32706615706242126 | $-6.31 | -2.523% | 2.642% |
| S54_residual_fade_sideline | validation | severe | 23 | 39.1% | 0.3238620559518233 | $-3.89 | -1.556% | 2.060% |

- Decyzja dla `S54_residual_fade_sideline`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 104, 'validation': 80}.
- Udział reżimów 15m: {'UP': 0.299, 'DOWN': 0.284, 'SIDELINE': 0.417}.

Kapitał $250, jeden wspólny rachunek SOL+XRP. Base 5/2 bps, stress 8/5, severe 10/10. Okno ograniczone do cache lokalnego.
