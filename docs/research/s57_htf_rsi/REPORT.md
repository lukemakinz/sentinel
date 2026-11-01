# S57 — 4h RSI extreme, BTC+SOL+XRP

Hash protokołu: `c7af1ebcf167f01bc57c71b76daeea446b4375e8e2ef0efc2fdc6a0e615fb996`.

Ten sam trigger S40 (RSI 20/80 na 4h), inny klaster i okno. Dwie wypłaty: 2.5R/36h oraz oryginalny 8R trail S40. Charakterystyka, nie zgoda na live.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S57_rsi_2p5_time | development | base | 3 | 33.3% | 0.12756788029178276 | $-0.87 | -0.349% | 0.544% |
| S57_rsi_2p5_time | development | stress | 3 | 33.3% | 0.05668484347221275 | $-0.94 | -0.377% | 0.529% |
| S57_rsi_2p5_time | development | severe | 4 | 0.0% | 0.0 | $-1.50 | -0.602% | 0.602% |
| S57_rsi_2p5_time | validation | base | 2 | 50.0% | 0.39875991256105253 | $-0.30 | -0.119% | 0.440% |
| S57_rsi_2p5_time | validation | stress | 2 | 50.0% | 0.3790122952399517 | $-0.31 | -0.123% | 0.387% |
| S57_rsi_2p5_time | validation | severe | 2 | 50.0% | 0.35684333309468824 | $-0.32 | -0.127% | 0.342% |

- Decyzja dla `S57_rsi_2p5_time`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 14, 'validation': 11}.

| S57_rsi_patient_runner | development | base | 3 | 0.0% | 0.0 | $-1.47 | -0.586% | 0.625% |
| S57_rsi_patient_runner | development | stress | 3 | 0.0% | 0.0 | $-1.47 | -0.588% | 0.600% |
| S57_rsi_patient_runner | development | severe | 4 | 0.0% | 0.0 | $-1.97 | -0.788% | 0.788% |
| S57_rsi_patient_runner | validation | base | 2 | 100.0% | Infinity | $0.08 | 0.032% | 0.235% |
| S57_rsi_patient_runner | validation | stress | 2 | 50.0% | 0.10934717313395143 | $-0.44 | -0.176% | 0.387% |
| S57_rsi_patient_runner | validation | severe | 2 | 50.0% | 0.0917730784227461 | $-0.45 | -0.180% | 0.342% |

- Decyzja dla `S57_rsi_patient_runner`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 14, 'validation': 11}.

