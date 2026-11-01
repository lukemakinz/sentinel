# S79 — Book B liquidation snapback

Hash protokołu: `a0de0850c574d95778084868d4ad6b1a38e48e9d698c7efeffff6fbff14ec712`.

Kapitał $250, ryzyko $15/trade, max 2 pozycje. Cel **$5.0/dzień**.

| Trasa | Okno | Scenariusz | Tradów | PF | PnL | Opłaty | $/dzień | Gap $5 | $5? |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| S79_book_b_liq | development | base | 164 | 0.5306187532275396 | $-82.11 | $0.00 | $-0.537 | $5.54 | no |
| S79_book_b_liq | development | stress | 77 | 0.31346647606559724 | $-85.51 | $0.00 | $-0.559 | $5.56 | no |
| S79_book_b_liq | development | severe | 50 | 0.1395958611851409 | $-89.99 | $0.00 | $-0.588 | $5.59 | no |
| S79_book_b_liq | validation | base | 159 | 0.4457105977775844 | $-85.52 | $0.00 | $-0.930 | $5.93 | no |
| S79_book_b_liq | validation | stress | 74 | 0.23127002794456797 | $-88.36 | $0.00 | $-0.960 | $5.96 | no |
| S79_book_b_liq | validation | severe | 55 | 0.1608313727602662 | $-90.67 | $0.00 | $-0.986 | $5.99 | no |
- Decyzja `S79_book_b_liq`: **REJECTED_AT_DEVELOPMENT_GATE**.

| S79_book_b_liq_confirmed | development | base | 113 | 0.65449821521376 | $-41.55 | $0.00 | $-0.272 | $5.27 | no |
| S79_book_b_liq_confirmed | development | stress | 91 | 0.3345126707963506 | $-83.69 | $0.00 | $-0.547 | $5.55 | no |
| S79_book_b_liq_confirmed | development | severe | 62 | 0.28016405480014983 | $-84.05 | $0.00 | $-0.549 | $5.55 | no |
| S79_book_b_liq_confirmed | validation | base | 100 | 0.7770435404067154 | $-21.50 | $0.00 | $-0.234 | $5.23 | no |
| S79_book_b_liq_confirmed | validation | stress | 93 | 0.420999542765107 | $-68.18 | $0.00 | $-0.741 | $5.74 | no |
| S79_book_b_liq_confirmed | validation | severe | 77 | 0.254186382976297 | $-86.36 | $0.00 | $-0.939 | $5.94 | no |
- Decyzja `S79_book_b_liq_confirmed`: **REJECTED_AT_DEVELOPMENT_GATE**.

