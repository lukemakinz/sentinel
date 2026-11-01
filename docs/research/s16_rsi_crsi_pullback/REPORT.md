# S16 — RSI(2)/Connors RSI pullback w trendzie (base vs confluence SMC)

Hash zamrożonego protokołu: `9a0ec42898e79c07fe19c57f2ee72326be84787f1e46af855f1dea47812f8452`.

To badanie retrospektywne. BTC nie jest używany — sygnał liczony wyłącznie z ceny handlowanego instrumentu.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| base | development | base | 142 | 46.5% | 0.4463522597831191 | $-14.80 | -5.920% | 6.004% |
| base | development | stress | 79 | 31.6% | 0.17323012458526182 | $-14.63 | -5.852% | 6.038% |
| base | development | severe | 68 | 25.0% | 0.09215810850395072 | $-15.04 | -6.018% | 6.018% |

- Decyzja dla `base`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 4098, 'validation': 1293, 'retrospective_evaluation': 3775}.

| confluence | development | base | 149 | 47.0% | 0.474938744035 | $-15.16 | -6.063% | 6.063% |
| confluence | development | stress | 119 | 38.7% | 0.29549954047111365 | $-15.01 | -6.004% | 6.004% |
| confluence | development | severe | 99 | 37.4% | 0.23425378854905335 | $-14.96 | -5.983% | 6.066% |

- Decyzja dla `confluence`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 1009, 'validation': 336, 'retrospective_evaluation': 847}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako „najmniej zła”. Confluence (H2) jest ściśle podzbiorem base (H1) — jeśli confluence wygrywa, to dlatego że filtr strukturalny podniósł jakość, a nie dlatego że złapał inne transakcje.

Kapitał: $250; jeden wspólny cash/pending/position; stałe ryzyko $0,50; notional do $125; dźwignia do 5x. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
