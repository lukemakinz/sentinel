# Book B — shared risk (S82)

**Moduł:** `backend/l1_filter/book_b_shared_risk.py`  
**Backtest:** `docs/research/s82_book_b_macro_rm/`

## Idea

Book B używa **tych samych wskaźników co Book A** (breadth, vol BTC), plus:

- **Filtr:** brak macro gdy `vol_pct > 78%` lub `breadth < 35%` lub BTC &lt; SMA200.
- **Skala `risk_scale` na sygnał:** większa gdy Book A jest **przycięty** (complement 0.35–1.0), mniejsza gdy vol rośnie.
- **Execution:** $8 risk, DD halt 28%, daily loss 5%, 3 straty z rzędu → stop.

Simulator: `signal['risk_scale']` mnoży budżet ryzyka (`cluster_scalp_simulator`).

## Porównanie (validation)

Zobacz `s82_book_b_macro_rm/REPORT.md` — S82 vs surowe S80.
