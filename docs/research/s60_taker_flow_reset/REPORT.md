# S60 — taker-flow flush then rebuild, 2.5R

Hash protokołu: `b28cb2986842c68268a4771eb3be106d5e51d519486ec4e76197ca338f5b8680`.

Flush agresywnego takera, potem rebuild z 4h trendem. 2.5R. To nie jest strojenie progów OI z S47.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S60_flow_reset_15m | development | base | 73 | 43.8% | 1.1815080285135238 | $3.36 | 1.345% | 2.053% |
| S60_flow_reset_15m | development | stress | 74 | 39.2% | 0.8650549378063163 | $-2.62 | -1.048% | 3.213% |
| S60_flow_reset_15m | development | severe | 72 | 36.1% | 0.5991778635747391 | $-7.80 | -3.120% | 4.102% |
| S60_flow_reset_15m | validation | base | 27 | 33.3% | 0.7908536154036285 | $-1.54 | -0.615% | 1.510% |
| S60_flow_reset_15m | validation | stress | 27 | 33.3% | 0.6120657183696542 | $-2.91 | -1.166% | 1.775% |
| S60_flow_reset_15m | validation | severe | 27 | 25.9% | 0.38902529050081824 | $-4.71 | -1.885% | 2.271% |

- Decyzja dla `S60_flow_reset_15m`: **REJECTED_AT_VALIDATION_GATE**.
- Kandydaty surowe: {'development': 83, 'validation': 29}.

| S60_flow_reset_5m | development | base | 258 | 36.8% | 0.7197281761699664 | $-14.77 | -5.909% | 6.034% |
| S60_flow_reset_5m | development | stress | 134 | 29.9% | 0.4942044280074459 | $-14.90 | -5.959% | 6.007% |
| S60_flow_reset_5m | development | severe | 111 | 27.0% | 0.37551252495304466 | $-15.09 | -6.038% | 6.044% |
| S60_flow_reset_5m | validation | base | 135 | 26.7% | 0.519811540507015 | $-14.99 | -5.995% | 6.050% |
| S60_flow_reset_5m | validation | stress | 100 | 27.0% | 0.3554864460496664 | $-15.23 | -6.093% | 6.093% |
| S60_flow_reset_5m | validation | severe | 77 | 24.7% | 0.176510883373126 | $-14.67 | -5.870% | 6.014% |

- Decyzja dla `S60_flow_reset_5m`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 452, 'validation': 221}.

