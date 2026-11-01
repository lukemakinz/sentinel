# S56 — funding carry through settlement

Hash protokołu: `d92d685a9cad3055414b56b6a2bfac9737a82f30bc8302a1a71f6bf7d82b2b21`.

Ekstrema fundingu: short gdy longi płacą, long gdy shorty płacą. Wejście 1h przed 00/08/16 UTC. Target 2.5R, bez trailing. To nie jest 15m fade z S51.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD | funding PnL |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| S56_carry_through_settlement | development | base | 270 | 43.0% | 0.6252542490299695 | $-12.07 | -4.829% | 5.031% | $0.44 |
| S56_carry_through_settlement | development | stress | 220 | 37.3% | 0.4466919071578115 | $-15.09 | -6.035% | 6.055% | $0.31 |
| S56_carry_through_settlement | development | severe | 147 | 32.0% | 0.29997252379585404 | $-15.02 | -6.009% | 6.009% | $0.18 |
| S56_carry_through_settlement | validation | base | 117 | 49.6% | 1.0316977781122263 | $0.45 | 0.181% | 1.043% | $0.25 |
| S56_carry_through_settlement | validation | stress | 117 | 41.0% | 0.7598017881578241 | $-3.72 | -1.486% | 1.765% | $0.23 |
| S56_carry_through_settlement | validation | severe | 117 | 34.2% | 0.5503597632231042 | $-7.69 | -3.076% | 3.135% | $0.21 |

- Decyzja dla `S56_carry_through_settlement`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 386, 'validation': 147}.

| S56_carry_and_revert | development | base | 270 | 41.5% | 0.7600925403752 | $-11.75 | -4.701% | 5.184% | $0.42 |
| S56_carry_and_revert | development | stress | 227 | 39.2% | 0.6614201045593977 | $-13.82 | -5.529% | 6.013% | $0.31 |
| S56_carry_and_revert | development | severe | 134 | 35.8% | 0.4725853341645753 | $-14.62 | -5.849% | 6.024% | $0.16 |
| S56_carry_and_revert | validation | base | 117 | 47.9% | 1.1569533866744712 | $3.82 | 1.528% | 1.993% | $0.25 |
| S56_carry_and_revert | validation | stress | 117 | 45.3% | 0.9887753992893249 | $-0.28 | -0.111% | 2.342% | $0.23 |
| S56_carry_and_revert | validation | severe | 117 | 40.2% | 0.7771090348385953 | $-5.75 | -2.300% | 3.002% | $0.21 |

- Decyzja dla `S56_carry_and_revert`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 386, 'validation': 147}.

Kapitał $250, jeden wspólny rachunek SOL+XRP. Base 5/2 bps, stress 8/5, severe 10/10.
