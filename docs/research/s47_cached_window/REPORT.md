# S47 — OI reset→rebuild (cached SOL+XRP window)

Hash protokołu charakterystyki: `d98bd058680b3d90030cd66cabfdfa0aa2cd7851a11d67f715623b881d0b2162`.

Zamrożony sygnał S47 (sweep 1h → reset OI → MSS 15m → rebuild), target 2.5R, hold 240 min, bez trailing. To nie jest 6-fold gate z protocol.json i nie jest zgodą na live.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S47_oi_state_transition | development | base | 1 | 100.0% | Infinity | $0.26 | 0.105% | 0.058% |
| S47_oi_state_transition | development | stress | 1 | 100.0% | Infinity | $0.22 | 0.087% | 0.054% |
| S47_oi_state_transition | development | severe | 1 | 100.0% | Infinity | $0.17 | 0.067% | 0.053% |
| S47_oi_state_transition | validation | base | 1 | 100.0% | Infinity | $0.43 | 0.172% | 0.062% |
| S47_oi_state_transition | validation | stress | 1 | 100.0% | Infinity | $0.41 | 0.163% | 0.061% |
| S47_oi_state_transition | validation | severe | 1 | 100.0% | Infinity | $0.38 | 0.154% | 0.059% |

- Decyzja dla `S47_oi_state_transition`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 1, 'validation': 1}.

