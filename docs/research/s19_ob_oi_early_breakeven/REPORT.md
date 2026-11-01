# S19 — S18 (OB + OI) z wcześniejszą aktywacją breakeven/trailingu

Hash zamrożonego protokołu: `ac77d2591f162212ff8c3e0f9a5e869c0a68b5a3f1281159faa67d575a236574`.

To badanie retrospektywne. Jedyna zmiana względem S18 H1: próg aktywacji breakeven+trailing (0.5R zamiast 1.0R) i w H2 dodatkowo węższy trailing (1.0xATR).

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S19_ob_oi_early_breakeven | development | base | 143 | 55.9% | 0.5829883657271172 | $-10.54 | -4.218% | 4.911% |
| S19_ob_oi_early_breakeven | development | stress | 145 | 49.0% | 0.423132469578742 | $-14.04 | -5.614% | 5.793% |
| S19_ob_oi_early_breakeven | development | severe | 108 | 40.7% | 0.14464163136107647 | $-14.97 | -5.989% | 6.046% |

- Decyzja dla `S19_ob_oi_early_breakeven`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 196, 'validation': 62, 'retrospective_evaluation': 158}.

| S19_ob_oi_early_breakeven_tight_trail | development | base | 143 | 55.9% | 0.5191323250586377 | $-11.42 | -4.567% | 5.177% |
| S19_ob_oi_early_breakeven_tight_trail | development | stress | 126 | 47.6% | 0.31649498090940104 | $-14.64 | -5.856% | 6.003% |
| S19_ob_oi_early_breakeven_tight_trail | development | severe | 108 | 40.7% | 0.15197077843478818 | $-15.05 | -6.021% | 6.077% |

- Decyzja dla `S19_ob_oi_early_breakeven_tight_trail`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 196, 'validation': 62, 'retrospective_evaluation': 158}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako „najmniej zła”. To badanie izoluje dokładnie jedną zmienną (próg aktywacji) względem S18 H1 — sygnał wejścia jest identyczny bit-w-bit.

Kapitał: $250; jeden wspólny cash/pending/position; stałe ryzyko $0,50; notional do $125; dźwignia do 5x. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
