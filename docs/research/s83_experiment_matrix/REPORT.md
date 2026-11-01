# S83 — experiment matrix

## Wnioski (validation)

- **RM na A** nadal najważniejsze; warianty top3 / mom3% / biweekly — porównaj tabelę.
- **Book B S83 (quiet Donchian):** **+$0,10/d** na validation (8 tradów) — sprawdź **CONCLUSIONS.md** (dev ujemny).
- **A bez nogi BTC:** **+$0,31/d** validation — BTC tylko jako filtr SMA200.
- **Greedy A+B:** **+$0,42/d**, gap **~$4,59** do $5 (najlepszy replay; mała próba B).

### Top Book A (validation $/dzień)

- `A_RM_noBTC`: **$0.310/d**, PnL $28.49
- `A_RM_base`: **$-0.042/d**, PnL $-3.86
- `A_RM_top3`: **$-0.042/d**, PnL $-3.86
- `A_RM_mom3pct`: **$-0.042/d**, PnL $-3.86
- `A_RM_tight`: **$-0.042/d**, PnL $-3.86

### Top Book B (validation $/dzień)

- `B_S83_quiet`: **$0.105/d**, PnL $9.68, trades 8
- `B_complement`: **$0.000/d**, PnL $0.00, trades 0
- `B_CPI_only`: **$0.000/d**, PnL $0.00, trades 0
- `B_S82`: **$-0.018/d**, PnL $-1.64, trades 1

### Greedy A+B (validation)

- `A_RM_noBTC+B_S83_quiet`: **$0.415/d**, gap $4.59

Pełna lista: `experiments.json`.
