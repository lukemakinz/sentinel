# S62 — dollar-ratchet + day halt na 4h Donchian-20

Hash protokołu: `64be62ccf378601936fc8321533689882b5d4d40b05bc19e6f62105f1093d61f`.

S61 na 15m pogorszył wynik. Tu ten sam risk book na holdzie 36h. Sygnał Donchian-20 z S55, bez zmiany lookbacku.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD | mean R |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ratchet_all | development | base | 68 | 51.5% | 1.0536911484500189 | $0.72 | 0.289% | 2.104% | 0.022 |
| ratchet_all | development | stress | 68 | 48.5% | 0.9045105566019748 | $-1.34 | -0.537% | 2.590% | -0.039 |
| ratchet_all | development | severe | 68 | 48.5% | 0.8278758066096236 | $-2.44 | -0.974% | 2.723% | -0.072 |
| ratchet_all | validation | base | 35 | 37.1% | 0.5517295175575664 | $-3.53 | -1.414% | 2.049% | -0.203 |
| ratchet_all | validation | stress | 35 | 34.3% | 0.4255254457170067 | $-4.56 | -1.824% | 2.145% | -0.263 |
| ratchet_all | validation | severe | 33 | 36.4% | 0.5591217017187443 | $-3.23 | -1.292% | 1.907% | -0.197 |

- Decyzja dla `ratchet_all`: **REJECTED_AT_VALIDATION_GATE**.
- Halt diagnostics: {'development': 0, 'validation': 0}.

| ratchet_short | development | base | 68 | 51.5% | 1.0536911484500189 | $0.72 | 0.289% | 2.104% | 0.022 |
| ratchet_short | development | stress | 68 | 48.5% | 0.9045105566019748 | $-1.34 | -0.537% | 2.590% | -0.039 |
| ratchet_short | development | severe | 68 | 48.5% | 0.8278758066096236 | $-2.44 | -0.974% | 2.723% | -0.072 |
| ratchet_short | validation | base | 35 | 37.1% | 0.5517295175575664 | $-3.53 | -1.414% | 2.049% | -0.203 |
| ratchet_short | validation | stress | 35 | 34.3% | 0.4255254457170067 | $-4.56 | -1.824% | 2.145% | -0.263 |
| ratchet_short | validation | severe | 33 | 36.4% | 0.5591217017187443 | $-3.23 | -1.292% | 1.907% | -0.197 |

- Decyzja dla `ratchet_short`: **REJECTED_AT_VALIDATION_GATE**.
- Halt diagnostics: {'development': 0, 'validation': 0}.

