# S22 — S20 (OB + OI, cierpliwy exit) ze skalowaną wielkością pozycji

Hash zamrożonego protokołu: `6e7b114af1b953923e35db6374ddb8fd723724efe51aa357a3f96690345e47fd`.

To badanie retrospektywne. Jedyna zmiana względem S20 H1: wielkość pozycji (2x/4x). PF i R-multiples powinny być statystycznie takie same jak w S20 H1 — skalowanie NIE tworzy przewagi, tylko zmienia kwotę $ tej samej przewagi.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S22_ob_oi_2x_size | development | base | 118 | 44.9% | 1.0250700317038166 | $1.15 | 0.459% | 6.062% |
| S22_ob_oi_2x_size | development | stress | 114 | 42.1% | 0.794662374983583 | $-9.29 | -3.716% | 6.068% |
| S22_ob_oi_2x_size | development | severe | 81 | 35.8% | 0.5444890688618524 | $-14.37 | -5.748% | 6.103% |

- Decyzja dla `S22_ob_oi_2x_size`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 196, 'validation': 62, 'retrospective_evaluation': 158}.

| S22_ob_oi_4x_size | development | base | 90 | 46.7% | 0.9365592412425628 | $-2.86 | -1.143% | 6.164% |
| S22_ob_oi_4x_size | development | stress | 82 | 40.2% | 0.6681460064128695 | $-14.84 | -5.934% | 6.352% |
| S22_ob_oi_4x_size | development | severe | 30 | 20.0% | 0.2944152651034885 | $-14.51 | -5.804% | 6.017% |

- Decyzja dla `S22_ob_oi_4x_size`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 196, 'validation': 62, 'retrospective_evaluation': 158}.

## Interpretacja

Większy rozmiar pozycji nie naprawia problemu S20 (PF pod kosztem stress <1.0) — tylko powiększa kwotę tego samego, kruchego wyniku, w obie strony.

Kapitał: $250; jeden wspólny cash/pending/position. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
