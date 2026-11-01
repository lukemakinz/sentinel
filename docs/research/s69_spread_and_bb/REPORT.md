# S69 — fade spreadu SOL/XRP i powrót 4h Bollingera, cel $5/dzień

Hash protokołu: `9586e2a992a449643952400541783ca7a6ca17798262d0d4d981c1813675f95f`.

Z-score log-spreadu (beta 60, okno 20, próg 2) to odwrotność momentum S68. Bollinger 4h fade do środka wstęgi w ADX<25 to nie squeeze-breakout S13. Dwa sloty, $15/noga.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | $/dzień | Max DD | mean R | $5? |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| S69_spread_zscore | development | base | 4 | 50.0% | 1.8293583690513349 | $6.93 | $0.05 | 5.236% | 0.119 | nie |
| S69_spread_zscore | development | stress | 3 | 33.3% | 1.6561639493728373 | $5.71 | $0.04 | 7.125% | 0.127 | nie |
| S69_spread_zscore | development | severe | 1 | 0.0% | 0.0 | $-4.99 | $-0.03 | 3.891% | -0.333 | nie |
| S69_spread_zscore | validation | base | 1 | 100.0% | Infinity | $11.16 | $0.12 | 2.092% | 0.744 | nie |
| S69_spread_zscore | validation | stress | 1 | 100.0% | Infinity | $10.79 | $0.12 | 2.065% | 0.719 | nie |
| S69_spread_zscore | validation | severe | 1 | 100.0% | Infinity | $10.37 | $0.11 | 2.034% | 0.691 | nie |

- Decyzja dla `S69_spread_zscore`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 34, 'validation': 16}.

| S69_bb_mean_revert | development | base | 57 | 38.6% | 1.0163087802545732 | $3.87 | $0.03 | 19.627% | -0.005 | nie |
| S69_bb_mean_revert | development | stress | 57 | 38.6% | 0.9244559609897173 | $-18.17 | $-0.12 | 22.701% | -0.057 | nie |
| S69_bb_mean_revert | development | severe | 57 | 38.6% | 0.8341675716568319 | $-40.45 | $-0.26 | 28.103% | -0.111 | nie |
| S69_bb_mean_revert | validation | base | 16 | 12.5% | 0.19417323996362088 | $-70.46 | $-0.77 | 28.769% | -0.700 | nie |
| S69_bb_mean_revert | validation | stress | 16 | 12.5% | 0.17364254426534295 | $-74.48 | $-0.81 | 30.155% | -0.712 | nie |
| S69_bb_mean_revert | validation | severe | 16 | 12.5% | 0.15328426408597903 | $-78.68 | $-0.86 | 31.590% | -0.725 | nie |

- Decyzja dla `S69_bb_mean_revert`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 67, 'validation': 44}.

Nie jest to zgoda na live.
