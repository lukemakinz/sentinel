# S119 — Book A on a point-in-time universe

Protocol `protocol.json` (frozen before results). Frozen BOOK_A_ALT_RM + risk overlay,
2024-01-01..2026-10-01, $250, same simulator and daily-close panel for both universes.

| stress (12 bps) | total | return | $/day | Sharpe | max DD | 2024 | 2025 | 2026 | 95% lower $/day |
|---|---|---|---|---|---|---|---|---|---|
| fixed 5 coins (hindsight) | **+$160.1** | +64.1% | 0.160 | 1.38 | −$56.1 | +48.1 | +86.0 | +25.9 | +0.020 |
| point-in-time top 20 | **+$15.5** | +6.2% | 0.015 | 0.32 | −$27.8 | +7.0 | +5.2 | +3.2 | −0.028 |

## Decision: **REJECTED** (bootstrap lower bound <= 0)

About 90% of Book A's historical profit comes from its hindsight-selected coins
(SOL, XRP, DOGE, BNB, ETH). With the universe an investor could actually have
chosen at each point in time, the same rules earn +6% in 2.75 years: positive in
every year, but small and statistically indistinguishable from zero.

Book A's historical result is therefore not evidence of a durable edge; the
underlying trend-following logic shows at most a weak positive tendency.
