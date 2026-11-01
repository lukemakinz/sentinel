# S65 — mean reversion day/swing, $10 risk, cel $10/dzień

Hash protokołu: `9025751cf193e4b796c5812f39f4ca55e4a35299c0275afb77e734b37c429cd7`.

VWAP dip-reclaim w 4h trendzie (hold sesyjny) i RSI(2) Connors na dziennym. To nie jest wybicie S64 ani 1R scalp S49/S50. Ryzyko $10, SOL+XRP, $250.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | $/dzień | Max DD | mean R |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| S65_vwap_trend_dip | development | base | 92 | 13.0% | 0.5942636807229282 | $-59.11 | $-0.39 | 25.409% | -0.325 |
| S65_vwap_trend_dip | development | stress | 42 | 9.5% | 0.3119252165557044 | $-62.31 | $-0.41 | 25.006% | -0.605 |
| S65_vwap_trend_dip | development | severe | 23 | 8.7% | 0.07339594732656662 | $-62.84 | $-0.41 | 25.136% | -0.841 |
| S65_vwap_trend_dip | validation | base | 31 | 0.0% | 0.0 | $-63.26 | $-0.69 | 25.304% | -1.000 |
| S65_vwap_trend_dip | validation | stress | 23 | 0.0% | 0.0 | $-63.74 | $-0.69 | 25.495% | -1.000 |
| S65_vwap_trend_dip | validation | severe | 19 | 0.0% | 0.0 | $-63.61 | $-0.69 | 25.446% | -1.000 |

- Decyzja dla `S65_vwap_trend_dip`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 177, 'validation': 104}.

| S65_rsi2 | development | base | 1 | 100.0% | Infinity | $11.91 | $0.08 | 3.378% | 1.191 |
| S65_rsi2 | development | stress | 1 | 100.0% | Infinity | $11.61 | $0.08 | 3.334% | 1.161 |
| S65_rsi2 | development | severe | 1 | 100.0% | Infinity | $11.26 | $0.07 | 3.284% | 1.126 |
| S65_rsi2 | validation | base | 0 | 0.0% | — | $0.00 | $0.00 | 0.000% | 0.000 |
| S65_rsi2 | validation | stress | 0 | 0.0% | — | $0.00 | $0.00 | 0.000% | 0.000 |
| S65_rsi2 | validation | severe | 0 | 0.0% | — | $0.00 | $0.00 | 0.000% | 0.000 |

- Decyzja dla `S65_rsi2`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 4, 'validation': 2}.

Cel $10/dzień jest diagnostyką. Nie jest to zgoda na live.
