# Historical replay auction-replay-v1.2-intraday-management: M0 / M1 / M3

Period 2024-01-01 → 2026-10-01 (1004.0 days), targets: BTCUSDT, ETHUSDT, SOLUSDT, AVAXUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, MATICUSDT, LINKUSDT, BNBUSDT.
Candidates: 725. Rules are frozen for this retrospective run; this history is diagnostic, not a claim of out-of-sample performance.

## Verdict
- M1 trend filter: no detectable effect (CI +0.000..+0.009 R).
- M3 global context: no detectable effect (CI -0.020..+0.009 R).
- M0 baseline edge is not distinguishable from zero (CI -0.164..+0.075 R per candidate).
- P1 scale + protected stop: has no detectable effect (CI -0.075..+0.164 R per candidate).
- P2 scale + runner trail: has no detectable effect (CI -0.075..+0.164 R per candidate).

## Policies (live shadow cost model)

| | kept | filled | WR | E/trade R | E/candidate R | total R | PF | max DD R | $/day | cost R |
|---|---|---|---|---|---|---|---|---|---|---|
| M0 baseline | 725 | 721 | 0.3814 | -0.0411 | -0.0409 | -29.63 | 0.932 | -58.91 | -0.037 | 0.035 |
| M1 + trend | 723 | 719 | 0.3825 | -0.0383 | -0.038 | -27.53 | 0.937 | -58.91 | -0.034 | 0.035 |
| M3 + global | 709 | 705 | 0.3801 | -0.0472 | -0.0459 | -33.31 | 0.922 | -60.63 | -0.041 | 0.035 |

$/day assumes $1.25 per 1R (0.5% risk on $250). Target: $5/day.

## Paired uplift vs M0 (per candidate, day-block bootstrap 95% CI)

- M1 − M0: 0.0029 R, CI [0.0, 0.009], P(≤0) 0.3628
- M3 − M0: -0.0051 R, CI [-0.02, 0.0087], P(≤0) 0.7556
- M0 expectancy per candidate: -0.0409 R, CI [-0.1637, 0.0746]
- Mean M0 outcome of candidates vetoed: M1 -1.0499 R, M3 0.2301 R (negative = veto removed losers).

## Intraday management on the same fills

| policy | filled | TP1 hit | WR | E/trade R | E/candidate R | total R | PF | max DD R | $/day |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | 0 | None | None | None | 0.0 | 0.0 | None | 0.0 | 0.0 |
| P2 | 0 | None | None | None | 0.0 | 0.0 | None | 0.0 | 0.0 |

- P1 − P0: 0.0409 R/candidate, CI [-0.0746, 0.1637], P(≤0) 0.2378
- P2 − P0: 0.0409 R/candidate, CI [-0.0746, 0.1637], P(≤0) 0.2378

Three entry/filter policies and two preregistered management policies were evaluated retrospectively on one sample. Treat a CI that excludes 0 at 95% as suggestive only; Bonferroni for 4 uplift tests would require ~98.75%, followed by a true forward holdout.

## Stability by year (total R)

| year | candidates | M0 | M1 | M3 |
|---|---|---|---|---|
| 2024 | 278 | -28.54 | -28.54 | -30.55 |
| 2025 | 260 | -12.68 | -12.68 | -12.44 |
| 2026 | 187 | 11.59 | 13.69 | 9.68 |

## By symbol (total R)

| symbol | candidates | filled | M0 | M1 | M3 |
|---|---|---|---|---|---|
| ADAUSDT | 72 | 71 | 12.03 | 13.09 | 12.03 |
| AVAXUSDT | 76 | 76 | 22.51 | 23.56 | 20.53 |
| BNBUSDT | 99 | 99 | -9.46 | -9.46 | -8.37 |
| BTCUSDT | 70 | 70 | -10.99 | -10.99 | -9.89 |
| DOGEUSDT | 90 | 89 | -9.88 | -9.88 | -8.83 |
| ETHUSDT | 77 | 76 | -22.53 | -22.53 | -21.47 |
| LINKUSDT | 75 | 75 | -15.39 | -15.39 | -19.34 |
| MATICUSDT | 23 | 23 | 3.66 | 3.66 | 4.73 |
| SOLUSDT | 70 | 70 | 0.11 | 0.11 | -2.8 |
| XRPUSDT | 73 | 72 | 0.31 | 0.31 | 0.09 |

## M0 by global-context state at the candidate

| state | candidates | filled | M0 mean R / candidate |
|---|---|---|---|
| ALT_RISK_OFF | 154 | 154 | -0.0407 |
| ALT_RISK_ON | 152 | 152 | -0.1663 |
| BROAD_RISK_OFF | 96 | 96 | 0.3901 |
| BTC_LED_ALT_HEADWIND | 2 | 2 | -0.8461 |
| TRANSITION | 321 | 317 | -0.1054 |

Exit reasons: {'STOP': 397, 'TARGET': 181, 'TIME': 143, 'NONE': 4}

## Assumptions and deviations from live

- **data_quality**: candles_only (no historical order book / OI / CVD)
- **arm_latency_minutes**: 3.0
- **watched_pairs_in_m0_regime**: ['SOLUSDT']
- **fvg_zone**: absent (M0 does not use it)
- **breadth_universe**: point-in-time per quarter, top 20 by prior-month median daily quote volume, listed >= 730d, no Alpha-tag filter (no history)
- **costs**: live shadow cost model (plan_geometry)
- **overlap**: each candidate resolved independently; concurrent positions not netted
- **management_counterfactuals**: P1 scale 50% at 0.75R then cost-BE/closed-1m structure to 1.5R; P2 risk cut after 0.5R, scale 40% at 0.75R and 30% at 1.25R, then trail the 30% runner by 0.5R; both stop-first, costed, max 4h and flat before the UTC day changes

## Point-in-time breadth universes

- 2024Q1: SOLUSDT, AVAXUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, MATICUSDT, LINKUSDT, BNBUSDT, TRBUSDT, DOTUSDT, FILUSDT, NEARUSDT, DYDXUSDT, ATOMUSDT, LTCUSDT, FTMUSDT, BAKEUSDT, 1000SHIBUSDT, ETCUSDT, BCHUSDT
- 2024Q2: DOGEUSDT, 1000SHIBUSDT, BNBUSDT, AVAXUSDT, MATICUSDT, ADAUSDT, BCHUSDT, LINKUSDT, DOTUSDT, GALAUSDT, ETCUSDT, UNIUSDT, ATOMUSDT, RUNEUSDT, ZRXUSDT, EOSUSDT, THETAUSDT, ICPUSDT, DYDXUSDT, APEUSDT
- 2024Q3: SOLUSDT, PEOPLEUSDT, BNBUSDT, DOGEUSDT, XRPUSDT, AVAXUSDT, 1000SHIBUSDT, JASMYUSDT, NEARUSDT, FILUSDT, UNIUSDT, ENSUSDT, ADAUSDT, CRVUSDT, LINKUSDT, BCHUSDT, MATICUSDT, TRBUSDT, FTMUSDT, OPUSDT
- 2024Q4: SOLUSDT, REEFUSDT, XRPUSDT, BNBUSDT, DOGEUSDT, FTMUSDT, AAVEUSDT, AVAXUSDT, PEOPLEUSDT, NEARUSDT, LINKUSDT, ADAUSDT, FILUSDT, CRVUSDT, INJUSDT, 1000SHIBUSDT, LTCUSDT, OPUSDT, BCHUSDT, DOTUSDT
- 2025Q1: XRPUSDT, DOGEUSDT, SOLUSDT, BNBUSDT, ADAUSDT, LINKUSDT, HBARUSDT, AVAXUSDT, 1000SHIBUSDT, AAVEUSDT, LTCUSDT, CRVUSDT, XLMUSDT, DOTUSDT, ENSUSDT, UNIUSDT, APTUSDT, FILUSDT, TRXUSDT, FTMUSDT
- 2025Q2: SOLUSDT, XRPUSDT, DOGEUSDT, ADAUSDT, BNBUSDT, AVAXUSDT, LTCUSDT, LINKUSDT, AAVEUSDT, BCHUSDT, DOTUSDT, HBARUSDT, NEARUSDT, TRXUSDT, FILUSDT, 1000SHIBUSDT, CRVUSDT, XLMUSDT, APTUSDT, UNIUSDT
- 2025Q3: SOLUSDT, XRPUSDT, 1000PEPEUSDT, DOGEUSDT, SUIUSDT, ADAUSDT, AAVEUSDT, UNIUSDT, BNBUSDT, AVAXUSDT, BCHUSDT, LINKUSDT, OPUSDT, LTCUSDT, DOTUSDT, LPTUSDT, NEARUSDT, ARBUSDT, RVNUSDT, FILUSDT
- 2025Q4: SOLUSDT, DOGEUSDT, XRPUSDT, BNBUSDT, AVAXUSDT, SUIUSDT, 1000PEPEUSDT, LINKUSDT, ADAUSDT, WLDUSDT, LTCUSDT, AAVEUSDT, ARBUSDT, DOTUSDT, BCHUSDT, UNIUSDT, NEARUSDT, FILUSDT, TRXUSDT, XLMUSDT
- 2026Q1: SOLUSDT, ZECUSDT, XRPUSDT, DOGEUSDT, BNBUSDT, SUIUSDT, 1000PEPEUSDT, ADAUSDT, AVAXUSDT, BCHUSDT, LINKUSDT, AAVEUSDT, LTCUSDT, FILUSDT, UNIUSDT, NEARUSDT, LUNA2USDT, DOTUSDT, WLDUSDT, APTUSDT
- 2026Q2: SOLUSDT, XRPUSDT, DOGEUSDT, BNBUSDT, ZECUSDT, 1000PEPEUSDT, ADAUSDT, SUIUSDT, AVAXUSDT, LINKUSDT, BCHUSDT, FILUSDT, DOTUSDT, NEARUSDT, WLDUSDT, AAVEUSDT, LTCUSDT, TRXUSDT, FETUSDT, WIFUSDT
- 2026Q3: SOLUSDT, ZECUSDT, XRPUSDT, WLDUSDT, DOGEUSDT, BNBUSDT, NEARUSDT, ADAUSDT, 1000PEPEUSDT, SUIUSDT, ENAUSDT, TAOUSDT, XLMUSDT, AVAXUSDT, LINKUSDT, FILUSDT, BCHUSDT, ONDOUSDT, AAVEUSDT, LTCUSDT
