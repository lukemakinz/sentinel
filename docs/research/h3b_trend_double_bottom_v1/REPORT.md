# H3B — with-trend double bottom/top + RSI divergence (1h)

Protocol `protocol.json` (frozen before results). Plugin
`l2_agents/strategies/h3b_trend_double_bottom.py` (RESEARCH_ONLY, not enabled live),
replayed with the production snapshot composer, plan geometry and resolver.
10 symbols, 2024-01..2026-10, one position per symbol.

| costs | policy | trades | WR | mean R | total R | PF | cost R |
|---|---|---|---|---|---|---|---|
| base (5 bps) | H3B | 721 | 38.1% | −0.041 | −29.6 | 0.93 | 0.035 |
| base | + M1 trend | 719 | 38.3% | −0.038 | −27.5 | 0.94 | 0.035 |
| base | + M3 global | 705 | 38.0% | −0.047 | −33.3 | 0.92 | 0.035 |
| **stress (10 bps)** | **H3B** | **720** | **37.2%** | **−0.074** | **−53.3** | **0.88** | 0.034 |
| stress | + M1 trend | 718 | 37.3% | −0.071 | −51.2 | 0.89 | 0.034 |
| stress | + M3 global | 704 | 37.1% | −0.081 | −56.8 | 0.87 | 0.034 |

Total R by year (stress, H3B): 2024 −40.5, 2025 −16.8, 2026 +3.9.

## Decision: **REJECTED** (negative mean in stress; not positive every year)

* Economics fixed: costs ~0.035 R (vs 0.53 R for M0) thanks to 1-6% structural stops.
* Signal is ~random: S117 showed H3B entries indistinguishable from random entries.
* M1 adds nothing (H3B is already 4h-trend aligned); M3 slightly worse.
* Follow-ups: S117 (exit geometry) and S118 (timeframes, parameters, confluence)
  both rejected; see their reports.
