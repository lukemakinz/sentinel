# Book A — zamrożony risk overlay (RM_composite_v1)

**Status:** FREEZE po `docs/research/book_a_risk_overlay/` (2026-03).

## Po co

Sama bramka BTC &gt; SMA200 nie filtruje **chopu w hossie**. Overlay skaluje lub zeruje ekspozycję przed rebalance.

## Wskaźniki (research, forward 5d alty)

| Wskaźnik | Korelacja z fwd5 | Interpretacja |
|----------|------------------|---------------|
| `btc_vol_percentile` | **−0,14** | Wysoka vol BTC → słabsze kolejne dni altów |
| `mom_dispersion` | −0,11 | Skupiony momentum → gorszy fwd |
| `breadth_sma50` | **+0,09** | Szeroka breadth → lekko lepszy fwd |

## Reguły RM_composite_v1

Kod: `backend/l1_filter/book_a_risk_overlay.py`

1. **Bramka bazowa:** BTC &gt; SMA200 (bez zmian).
2. **Breadth:** jeśli &lt; 35% altów &gt; SMA50 → **0%** ekspozycja; inaczej skala `min(1, breadth/0.35)`.
3. **Vol BTC:** percentyl 20d vol w 252d — powyżej 75% liniowo tnij ekspozycję; **≥ 92% → 0%**.
4. **Drawdown konta:** DD ≥ 10% → ×0,5 ekspozycji; **≥ 18% → flat** do następnego rebalance.
5. **Sufit gross:** max **85%** kapitału w pozycjach.

## Wynik vs baseline (replay repo, $250)

| Okno | Baseline $/dzień | + RM_composite $/dzień | Max DD baseline | Max DD + RM |
|------|------------------:|------------------------:|----------------:|------------:|
| development | +1,18 | +1,31 | −12,5% | **−10,6%** |
| validation | **−0,21** | **−0,04** | −17,0% | **−11,1%** |

Gap do $5 (validation): **$5,04/d** (vs $5,21 baseline) — nadal daleko, ale **mniejsza strata i DD**.

## Operacja

- Używać `simulate_book_a(..., risk=BookARiskOverlayConfig())` lub domyślnego `BOOK_A_RISK_DEFAULT` z modułu.
- Paper: logować `exposure_mult` co tydzień z `risk_log`.

## Nie zmieniać bez nowego protokołu

- `min_breadth_sma50`, `vol_pct_*`, `drawdown_*` — już przetestowane na 2 oknach; brak grid search live.
