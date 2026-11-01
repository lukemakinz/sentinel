# R5 + S99 same-period allocation diagnostic

Method hash: `68ff1ea56f40209305009d1cfe0798fdec47e5080e2016caeae4f624088a52f8`.

Post-selection diagnostic only; the allocation was evaluated after S99 was known.

| Portfolio | Capital | Stress PnL | Return | $/month | Max DD |
|---|---:|---:|---:|---:|---:|
| Official R5: Book A $250 + cash $250 | $500 | $122.15 | 24.43% | $7.62 | 4.01% |
| S99 sleeve alone | $250 | $17.17 | 6.87% | $1.07 | 8.96% |
| Book A $250 + S99 $250 | $500 | $139.10 | 27.82% | $8.68 | 5.11% |

Daily PnL correlation: **0.026**.

The 1d Book A reproduction differs from the official 1m-ledger PnL by **$-0.22**; official R5 remains the benchmark.

Replacing cash with S99 added historical return but also introduced losses in months when R5 was flat. The allocation needs a fresh paper-forward clock before any promotion.
