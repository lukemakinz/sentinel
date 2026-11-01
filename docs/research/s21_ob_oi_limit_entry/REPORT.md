# S21 — S20 (OB + OI, cierpliwy exit) z limit entry w OTE (SMC) + killzone (ICT)

Hash zamrożonego protokołu: `d3239c5386ddd18d15766a71961b6b9e651283146f49a06f8f44b510fa2f61c7`.

To badanie retrospektywne. Jedyna zmiana względem S20 H1: mechanizm wypełnienia (resting limit w 50% strefy OB zamiast market na kolejnym otwarciu). H2 dodatkowo ogranicza wejścia do killzone London/NY.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S21_ob_oi_limit_entry | development | base | 17 | 29.4% | 0.10190249638010324 | $-4.64 | -1.855% | 1.855% |
| S21_ob_oi_limit_entry | development | stress | 15 | 26.7% | 0.03652199140548401 | $-4.98 | -1.991% | 1.991% |
| S21_ob_oi_limit_entry | development | severe | 15 | 20.0% | 0.03156491967781182 | $-5.75 | -2.300% | 2.300% |

- Decyzja dla `S21_ob_oi_limit_entry`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 196, 'validation': 62, 'retrospective_evaluation': 158}.

| S21_ob_oi_limit_entry_killzone | development | base | 10 | 30.0% | 0.135007548957345 | $-2.78 | -1.110% | 1.557% |
| S21_ob_oi_limit_entry_killzone | development | stress | 10 | 30.0% | 0.06602589815760575 | $-3.16 | -1.265% | 1.265% |
| S21_ob_oi_limit_entry_killzone | development | severe | 9 | 22.2% | 0.038813436625736296 | $-3.35 | -1.338% | 1.338% |

- Decyzja dla `S21_ob_oi_limit_entry_killzone`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 74, 'validation': 18, 'retrospective_evaluation': 55}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako „najmniej zła”.

Kapitał: $250; jeden wspólny cash/pending/position; stałe ryzyko $0,50; notional do $125; dźwignia do 5x. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
