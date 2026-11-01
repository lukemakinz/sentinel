# S25 — Strategia "$1 zysku": płaski cel 1:1 R:R, bez trailingu, na entry z S20

Hash zamrożonego protokołu: `cf4b8b6e0ed965b20db7595851cf553eb471f3350e128406a8a300cedf5ba898`.

To badanie retrospektywne. Ten sam entry co S20 H1; jedyna zmiana to płaski cel 1:1 zamiast cierpliwego trailingu, i wielkość pozycji tak dobrana, żeby cel realnie oznaczał ok. $1.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S25_flat_1r_standard_hold | development | base | 119 | 52.1% | 0.7927339359517348 | $-9.10 | -3.641% | 5.390% |
| S25_flat_1r_standard_hold | development | stress | 69 | 50.7% | 0.6927200233025838 | $-8.45 | -3.378% | 4.536% |
| S25_flat_1r_standard_hold | development | severe | 31 | 48.4% | 0.6554448453713849 | $-4.78 | -1.913% | 3.214% |

- Decyzja dla `S25_flat_1r_standard_hold`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 196, 'validation': 62, 'retrospective_evaluation': 158}.

| S25_flat_1r_fast_hold | development | base | 106 | 41.5% | 0.6238964187099898 | $-12.48 | -4.990% | 6.013% |
| S25_flat_1r_fast_hold | development | stress | 69 | 37.7% | 0.6024620064239706 | $-8.87 | -3.547% | 4.327% |
| S25_flat_1r_fast_hold | development | severe | 31 | 38.7% | 0.6664986142165394 | $-3.58 | -1.430% | 2.571% |

- Decyzja dla `S25_flat_1r_fast_hold`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 196, 'validation': 62, 'retrospective_evaluation': 158}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako „najmniej zła”.

Kapitał: $250; jeden wspólny cash/pending/position. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
