# S14 — BB + causal event PA/ICT/OB → kandydat shadow AI

Hash zamrożonego protokołu: `491b5d6215389ff2d6590279d8e44daffce649b4a122e67414c72367ae9903af`.

Wynik approve-all mierzy jakość mechanicznej kolejki, nie skuteczność AI. Historyczne miesiące były wcześniej oglądane i nie są nowym holdoutem.

| Trasa | Okno | Koszty | Kandydaci | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| squeeze_event_ob | development | base | 90 | 5 | 40.0% | 0.8771575408452563 | $-0.15 | -0.059% | 0.450% |
| squeeze_event_ob | development | stress | 90 | 0 | 0.0% | — | $0.00 | 0.000% | 0.000% |
| squeeze_event_ob | development | severe | 90 | 0 | 0.0% | — | $0.00 | 0.000% | 0.000% |

- Decyzja `squeeze_event_ob`: **REJECTED_AT_DEVELOPMENT_GATE**.

| liquidity_mss | development | base | 2 | 0 | 0.0% | — | $0.00 | 0.000% | 0.000% |
| liquidity_mss | development | stress | 2 | 0 | 0.0% | — | $0.00 | 0.000% | 0.000% |
| liquidity_mss | development | severe | 2 | 0 | 0.0% | — | $0.00 | 0.000% | 0.000% |

- Decyzja `liquidity_mss`: **REJECTED_AT_DEVELOPMENT_GATE**.

## Zasady interpretacji

- Wariant przegrywający development nie jest strojony ani otwierany na validation.
- Stress/severe ponownie stosuje znany przed wejściem filtr 4× kosztu i większy trade-through; mniejsza liczba filli nie oznacza odporności.
- Każdy zapisany sygnał zawiera twarde warunki, wektor 6 potwierdzeń, quorum, `setup_id` i stałą geometrię. AI może wyłącznie APPROVE/REJECT.
- Nawet przejście wszystkich historycznych bramek oznaczałoby tylko paper-forward.
