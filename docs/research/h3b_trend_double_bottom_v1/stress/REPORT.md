# Historical replay auction-replay-v1.2-intraday-management: M0 / M1 / M3

Period 2024-01-01 → 2026-10-01 (1004.0 days), targets: BTCUSDT, ETHUSDT, SOLUSDT, AVAXUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, MATICUSDT, LINKUSDT, BNBUSDT.
Candidates: 724. Rules are frozen for this retrospective run; this history is diagnostic, not a claim of out-of-sample performance.

## Verdict
- M1 trend filter: no detectable effect (CI +0.000..+0.009 R).
- M3 global context: no detectable effect (CI -0.020..+0.009 R).
- M0 baseline edge is not distinguishable from zero (CI -0.195..+0.042 R per candidate).
- P1 scale + protected stop: has no detectable effect (CI -0.042..+0.195 R per candidate).
- P2 scale + runner trail: has no detectable effect (CI -0.042..+0.195 R per candidate).

## Policies (live shadow cost model)

| | kept | filled | WR | E/trade R | E/candidate R | total R | PF | max DD R | $/day | cost R |
|---|---|---|---|---|---|---|---|---|---|---|
| M0 baseline | 724 | 720 | 0.3722 | -0.0741 | -0.0737 | -53.33 | 0.881 | -74.95 | -0.066 | 0.0344 |
| M1 + trend | 722 | 718 | 0.3733 | -0.0713 | -0.0707 | -51.2 | 0.886 | -74.95 | -0.064 | 0.0344 |
| M3 + global | 708 | 704 | 0.3707 | -0.0807 | -0.0784 | -56.78 | 0.871 | -76.44 | -0.071 | 0.0343 |

$/day assumes $1.25 per 1R (0.5% risk on $250). Target: $5/day.

## Paired uplift vs M0 (per candidate, day-block bootstrap 95% CI)

- M1 − M0: 0.0029 R, CI [0.0, 0.0092], P(≤0) 0.3628
- M3 − M0: -0.0048 R, CI [-0.0198, 0.0091], P(≤0) 0.7388
- M0 expectancy per candidate: -0.0737 R, CI [-0.1945, 0.0421]
- Mean M0 outcome of candidates vetoed: M1 -1.0653 R, M3 0.216 R (negative = veto removed losers).

## Intraday management on the same fills

| policy | filled | TP1 hit | WR | E/trade R | E/candidate R | total R | PF | max DD R | $/day |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | 0 | None | None | None | 0.0 | 0.0 | None | 0.0 | 0.0 |
| P2 | 0 | None | None | None | 0.0 | 0.0 | None | 0.0 | 0.0 |

- P1 − P0: 0.0737 R/candidate, CI [-0.0421, 0.1945], P(≤0) 0.1012
- P2 − P0: 0.0737 R/candidate, CI [-0.0421, 0.1945], P(≤0) 0.1012

Three entry/filter policies and two preregistered management policies were evaluated retrospectively on one sample. Treat a CI that excludes 0 at 95% as suggestive only; Bonferroni for 4 uplift tests would require ~98.75%, followed by a true forward holdout.

## Stability by year (total R)

| year | candidates | M0 | M1 | M3 |
|---|---|---|---|---|
| 2024 | 277 | -40.47 | -40.47 | -42.37 |
| 2025 | 260 | -16.77 | -16.77 | -16.46 |
| 2026 | 187 | 3.91 | 6.04 | 2.05 |

## By symbol (total R)

| symbol | candidates | filled | M0 | M1 | M3 |
|---|---|---|---|---|---|
| ADAUSDT | 72 | 71 | 11.01 | 12.08 | 11.01 |
| AVAXUSDT | 76 | 76 | 21.51 | 22.57 | 19.53 |
| BNBUSDT | 99 | 99 | -12.77 | -12.77 | -11.62 |
| BTCUSDT | 70 | 70 | -12.99 | -12.99 | -11.86 |
| DOGEUSDT | 90 | 89 | -11.26 | -11.26 | -10.19 |
| ETHUSDT | 77 | 76 | -26.99 | -26.99 | -25.91 |
| LINKUSDT | 75 | 75 | -16.29 | -16.29 | -20.25 |
| MATICUSDT | 22 | 22 | 0.54 | 0.54 | 1.63 |
| SOLUSDT | 70 | 70 | -0.64 | -0.64 | -3.54 |
| XRPUSDT | 73 | 72 | -5.43 | -5.43 | -5.58 |

## M0 by global-context state at the candidate

| state | candidates | filled | M0 mean R / candidate |
|---|---|---|---|
| ALT_RISK_OFF | 153 | 153 | -0.0762 |
| ALT_RISK_ON | 152 | 152 | -0.2037 |
| BROAD_RISK_OFF | 96 | 96 | 0.3747 |
| BTC_LED_ALT_HEADWIND | 2 | 2 | -0.8628 |
| TRANSITION | 321 | 317 | -0.14 |

Exit reasons: {'STOP': 400, 'TARGET': 176, 'TIME': 144, 'NONE': 4}

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
