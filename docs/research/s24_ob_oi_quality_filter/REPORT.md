# S24 — S20 (OB + OI, cierpliwy exit) z podniesionym progiem selektywności

Hash zamrożonego protokołu: `e9dcc5a2b27d42501399c303cc8da915daf587e000a920b79b3610437c0855ae`.

To badanie retrospektywne. Jedyna zmiana względem S20 H1: pojedynczy próg (ADX albo displacement) podniesiony — mniej, ale silniejszych kandydatów.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S24_ob_oi_stronger_regime | development | base | 68 | 45.6% | 0.9748410124824677 | $-0.43 | -0.171% | 3.891% |
| S24_ob_oi_stronger_regime | development | stress | 69 | 40.6% | 0.7781931114673304 | $-4.18 | -1.674% | 4.082% |
| S24_ob_oi_stronger_regime | development | severe | 73 | 31.5% | 0.3081923765021261 | $-12.54 | -5.017% | 5.294% |

- Decyzja dla `S24_ob_oi_stronger_regime`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 100, 'validation': 36, 'retrospective_evaluation': 63}.

| S24_ob_oi_stronger_structure | development | base | 22 | 45.5% | 1.3225760625223049 | $1.93 | 0.774% | 1.955% |
| S24_ob_oi_stronger_structure | development | stress | 23 | 39.1% | 0.5745827884581812 | $-2.96 | -1.182% | 2.405% |
| S24_ob_oi_stronger_structure | development | severe | 24 | 33.3% | 0.273193752743929 | $-5.44 | -2.175% | 2.691% |

- Decyzja dla `S24_ob_oi_stronger_structure`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 38, 'validation': 15, 'retrospective_evaluation': 41}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako „najmniej zła”.

Kapitał: $250; jeden wspólny cash/pending/position. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
