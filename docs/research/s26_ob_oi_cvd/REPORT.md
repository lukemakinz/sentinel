# S26 — CVD zamiast/plus OBV na entry z S20

Hash zamrożonego protokołu: `b480cdbd932a9371f098b9c7dd51f202177581a1cfce843af943c2c1a64e48ce`.

To badanie retrospektywne. Ten sam entry co S20 H1; H1 zamienia OBV na CVD, H2 dokłada dywergencję CVD do niezmienionego OBV.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S26_ob_oi_cvd_flow | development | base | 138 | 42.0% | 1.0391223071164368 | $1.36 | 0.543% | 4.269% |
| S26_ob_oi_cvd_flow | development | stress | 142 | 35.9% | 0.6881943713642434 | $-10.57 | -4.228% | 5.510% |
| S26_ob_oi_cvd_flow | development | severe | 106 | 33.0% | 0.41660457693975145 | $-13.64 | -5.456% | 6.013% |

- Decyzja dla `S26_ob_oi_cvd_flow`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 198, 'validation': 57, 'retrospective_evaluation': 167}.

| S26_ob_oi_cvd_divergence | development | base | 12 | 50.0% | 1.1335505050619172 | $0.35 | 0.141% | 1.251% |
| S26_ob_oi_cvd_divergence | development | stress | 12 | 50.0% | 0.8230729648123606 | $-0.47 | -0.188% | 1.300% |
| S26_ob_oi_cvd_divergence | development | severe | 13 | 46.2% | 0.4695750631993151 | $-1.68 | -0.672% | 1.542% |

- Decyzja dla `S26_ob_oi_cvd_divergence`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 17, 'validation': 4, 'retrospective_evaluation': 13}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako „najmniej zła”.

Kapitał: $250; jeden wspólny cash/pending/position. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
