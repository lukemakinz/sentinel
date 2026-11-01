# S13 — Bollinger jako router reżimu, nie magiczny sygnał

Hash zamrożonego protokołu: `bb64fa9bcfe410f2463190da87f0f6bec033d91b115c124ff5680eacbe8c7115`.

To badanie retrospektywne. Wszystkie użyte miesiące były wcześniej oglądane; nie są prawdziwym holdoutem. BTC jest wyłącznie rynkiem referencyjnym.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| squeeze_expansion | development | base | 37 | 27.0% | 0.43407406572893925 | $-7.04 | -2.815% | 3.355% |
| squeeze_expansion | development | stress | 14 | 21.4% | 0.38336411558955297 | $-2.60 | -1.042% | 1.304% |
| squeeze_expansion | development | severe | 1 | 100.0% | Infinity | $0.38 | 0.153% | 0.192% |

- Decyzja dla `squeeze_expansion`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 58, 'validation': 11, 'retrospective_evaluation': 47}.

| liquidity_failure_smt | development | base | 14 | 14.3% | 0.11951618876803624 | $-4.85 | -1.941% | 1.941% |
| liquidity_failure_smt | development | stress | 4 | 0.0% | 0.0 | $-1.99 | -0.798% | 0.871% |
| liquidity_failure_smt | development | severe | 3 | 0.0% | 0.0 | $-1.50 | -0.599% | 0.645% |

- Decyzja dla `liquidity_failure_smt`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 35, 'validation': 18, 'retrospective_evaluation': 17}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojoną dalej ani wybierana jako „najmniej zła”. Agent AI nie był historycznie symulowany: jego wartość można zmierzyć dopiero prospektywnie, porównując APPROVE i identycznie rozliczone REJECT.

Kapitał: $250; jeden wspólny cash/pending/position; stałe ryzyko $0,50; notional do $125; dźwignia do 5x. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
Stress i severe są testami wdrażalności z ponowną oceną filtra kosztowego oraz wymaganej penetracji; mogą więc mieć mniej filli niż base i nie są matched-cohort cost shockiem.
