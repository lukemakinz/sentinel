# S27 — S20 (OB + OI, cierpliwy exit) na altcoinach (XRP/SUI/DOGE)

Hash zamrożonego protokołu: `4d87ed48850baaf4fc8d9ea1b3a4bee7b33f9e4011f51e0a00d7307cea33d0aa`.

To badanie retrospektywne. Ten sam entry/exit co S20 H1; jedyna zmiana to uniwersum (altcoiny zamiast majorów) i w H2 dodatkowo dźwignia 30x.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S27_alts_standard_leverage | development | base | 127 | 36.2% | 0.4609460307664578 | $-13.26 | -5.305% | 5.927% |
| S27_alts_standard_leverage | development | stress | 98 | 32.7% | 0.27776885613761315 | $-14.32 | -5.730% | 6.039% |
| S27_alts_standard_leverage | development | severe | 83 | 30.1% | 0.1941862178117736 | $-14.48 | -5.792% | 6.022% |

- Decyzja dla `S27_alts_standard_leverage`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 178, 'validation': 56, 'retrospective_evaluation': 144}.

| S27_alts_30x_leverage | development | base | 84 | 34.5% | 0.40021501609358845 | $-11.66 | -4.664% | 5.017% |
| S27_alts_30x_leverage | development | stress | 78 | 34.6% | 0.31053246258572753 | $-12.44 | -4.976% | 5.238% |
| S27_alts_30x_leverage | development | severe | 66 | 27.3% | 0.14382586429000788 | $-14.70 | -5.878% | 6.042% |

- Decyzja dla `S27_alts_30x_leverage`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 178, 'validation': 56, 'retrospective_evaluation': 144}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako „najmniej zła”.

Kapitał: $250; jeden wspólny cash/pending/position na klaster 3 altcoinów. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
