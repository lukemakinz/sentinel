# S21c — Limit entry z ATR-owym ustępstwem (poprawka po S21)

Hash zamrożonego protokołu: `9136df6a65615062b6a614850c5b764374d803125c7d2c44a23ecadf859040e5`.

To badanie retrospektywne. Jedyna zmiana względem S21: cena limit to close(świeca dotknięcia) minus/plus 0.25xATR zamiast sztywnego środka strefy.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S21c_ob_oi_limit_concession | development | base | 104 | 42.3% | 0.849540459810739 | $-4.18 | -1.673% | 3.960% |
| S21c_ob_oi_limit_concession | development | stress | 101 | 41.6% | 0.6302134171786369 | $-9.62 | -3.849% | 4.431% |
| S21c_ob_oi_limit_concession | development | severe | 91 | 35.2% | 0.38781736829593644 | $-13.06 | -5.224% | 5.337% |

- Decyzja dla `S21c_ob_oi_limit_concession`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 196, 'validation': 62, 'retrospective_evaluation': 158}.

| S21c_ob_oi_limit_concession_killzone | development | base | 34 | 41.2% | 0.911030225693766 | $-0.83 | -0.332% | 1.980% |
| S21c_ob_oi_limit_concession_killzone | development | stress | 33 | 42.4% | 0.7714145777995368 | $-2.05 | -0.820% | 1.995% |
| S21c_ob_oi_limit_concession_killzone | development | severe | 29 | 27.6% | 0.4612480446775943 | $-4.94 | -1.975% | 2.155% |

- Decyzja dla `S21c_ob_oi_limit_concession_killzone`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 74, 'validation': 18, 'retrospective_evaluation': 55}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako „najmniej zła”.

Kapitał: $250; jeden wspólny cash/pending/position. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
