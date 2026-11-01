# S116 — regime atlas and router (v1.1)

Protocol `protocol.json` (v1.1 frozen before results). $500 in four $125 sleeves:
BOOK_A, BOOK_B, BTC_SMA200_LONG, S115_A. Regime = BTC daily trend (UP/SIDEWAYS/DOWN,
SMA100 + slope) x volatility (HIGH/LOW vs trailing-year median), causal (t-1).
One documented data repair (XRPUSDT 2023-11-30 12:35 corrupted archive volume).

## Decision: **REJECTED** — the router enabled no cell

No stream/regime cell met the frozen rule (>=100 days or >=50 trades, weekly
t >= 2.9, positive in both 2023 and 2024). Closest: BOOK_A in UP_HIGH (t = 2.18).

## Why this is the right outcome: regime-conditional results flip sign

Total $ per cell, development 2023-2024 vs diagnostic 2025-2026 (stress costs):

| stream | cell | development | diagnostic |
|---|---|---|---|
| BOOK_A | UP_LOW | −31.7 | **+50.5** |
| BOOK_A | UP_HIGH | **+66.8** (t 2.18) | 4 days only |
| BTC_SMA200_LONG | DOWN_HIGH | +24.2 | **−56.8** |
| BTC_SMA200_LONG | SIDEWAYS_LOW | +63.0 | +95.4 (only consistent cell) |
| S115_A | UP_LOW | −2.1 | **+203.4** |
| S115_A | SIDEWAYS_LOW | **+46.2** | −25.8 |
| BOOK_B | UP_HIGH | −7.3 | 4 days only |

A looser router (e.g. t >= 1.5 as in v1.0) would have enabled cells such as
BTC_SMA200 in DOWN_HIGH or S115 in SIDEWAYS_LOW that then lost money. With daily
BTC regimes and these streams, "strategy X works in regime Y" is not stable
enough to trade. The regime mix itself shifted (UP_HIGH: 244 days in 2023-2024,
4 days in 2025-2026), so cells are also thinly populated out of sample.

## What did hold: diversification, not timing

| always-on (same risk layer) | $/day on $500 | Sharpe | max DD | month-block 95% lower |
|---|---|---|---|---|
| development 2023-2024 | +0.157 | 0.80 | −$74.9 | −0.059 |
| diagnostic 2025-2026 | +0.356 | 1.36 | −$83.4 | +0.004 |

Positive in both windows, but small and with the Book A/B contamination caveat
(2025-2026 is not a clean holdout). True test = frozen paper-forward.

## Implications

* Do not route sleeves by daily BTC regime; use the regime as a risk/veto layer at most.
* Keep diversified always-on sleeves with vol targeting and the portfolio brake.
* Intraday plugin selection by 4h/1h state remains a separate, untested question.
