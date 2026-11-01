# S23 — S20 (OB + OI, cierpliwy exit) na szerszym uniwersum (6 symboli)

Hash zamrożonego protokołu: `dc7bc05015f09c824c4e9f09fc97f17c0785d8abe12a5141c1ce80bc1604f49c`.

To badanie retrospektywne. Jedyna zmiana względem S20 H1: dołożone ADA/XRP/DOGE, wciąż JEDNA globalna pozycja na cały klaster.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S23_ob_oi_six_symbols | development | base | 229 | 42.4% | 0.8604441932580378 | $-7.63 | -3.051% | 4.908% |
| S23_ob_oi_six_symbols | development | stress | 164 | 39.0% | 0.5517954140790061 | $-14.71 | -5.885% | 6.026% |
| S23_ob_oi_six_symbols | development | severe | 131 | 32.8% | 0.40924637440963557 | $-14.91 | -5.963% | 6.019% |

- Decyzja dla `S23_ob_oi_six_symbols`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 382, 'validation': 115, 'retrospective_evaluation': 297}.
- Fille per symbol (development/base): {'ETHUSDT': 47, 'SOLUSDT': 41, 'BNBUSDT': 42, 'ADAUSDT': 39, 'XRPUSDT': 40, 'DOGEUSDT': 20}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako „najmniej zła”.

Kapitał: $250; jeden wspólny cash/pending/position na cały klaster 6 symboli. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
