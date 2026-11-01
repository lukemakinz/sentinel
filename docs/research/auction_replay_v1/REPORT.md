# Historical replay auction-replay-v1: M0 / M1 / M3

Period 2024-01-01 → 2026-10-01 (1004.0 days), targets: BTCUSDT, ETHUSDT, SOLUSDT, AVAXUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, MATICUSDT, LINKUSDT, BNBUSDT.
Candidates: 123562. Frozen rules, zero fitted parameters: the whole period is out-of-sample for these policies.

## Verdict
- M1 trend filter: improves M0 per candidate (CI +0.032..+0.040 R).
- M3 global context: improves M0 per candidate (CI +0.018..+0.026 R).
- M0 baseline edge is negative (CI -0.296..-0.277 R per candidate).

## Policies (live shadow cost model)

| | kept | filled | WR | E/trade R | E/candidate R | total R | PF | max DD R | $/day | cost R |
|---|---|---|---|---|---|---|---|---|---|---|
| M0 baseline | 123562 | 36219 | 0.3012 | -0.978 | -0.2867 | -35420.96 | 0.255 | -35423.06 | -44.1 | 0.5264 |
| M1 + trend | 107674 | 31556 | 0.3008 | -0.9827 | -0.251 | -31009.99 | 0.254 | -31012.09 | -38.608 | 0.529 |
| M3 + global | 113147 | 33007 | 0.3005 | -0.9898 | -0.2644 | -32668.99 | 0.252 | -32671.1 | -40.674 | 0.5336 |

$/day assumes $1.25 per 1R (0.5% risk on $250). Target: $5/day.

## Paired uplift vs M0 (per candidate, day-block bootstrap 95% CI)

- M1 − M0: 0.0357 R, CI [0.0316, 0.0397], P(≤0) 0.0
- M3 − M0: 0.0223 R, CI [0.0183, 0.0263], P(≤0) 0.0
- M0 expectancy per candidate: -0.2867 R, CI [-0.2957, -0.2773]
- Mean M0 outcome of candidates vetoed: M1 -0.2776 R, M3 -0.2642 R (negative = veto removed losers).

Three pre-registered policies, zero fitted parameters. Treat a CI that excludes 0 at 95% as suggestive only; Bonferroni for 2 uplift tests would require ~97.5%.

## Stability by year (total R)

| year | candidates | M0 | M1 | M3 |
|---|---|---|---|---|
| 2024 | 43368 | -11760.18 | -10438.29 | -10968.41 |
| 2025 | 45285 | -13529.47 | -11787.24 | -12165.5 |
| 2026 | 34909 | -10131.3 | -8784.46 | -9535.08 |

## By symbol (total R)

| symbol | candidates | filled | M0 | M1 | M3 |
|---|---|---|---|---|---|
| ADAUSDT | 13260 | 3434 | -2861.39 | -2441.21 | -2577.52 |
| AVAXUSDT | 13761 | 4118 | -3541.41 | -2974.33 | -3128.33 |
| BNBUSDT | 14045 | 4445 | -5256.83 | -4565.22 | -4750.33 |
| BTCUSDT | 13009 | 4016 | -4884.9 | -4414.81 | -4884.9 |
| DOGEUSDT | 13480 | 3799 | -3377.38 | -2994.28 | -3111.79 |
| ETHUSDT | 12297 | 3437 | -3563.61 | -3206.16 | -3563.61 |
| LINKUSDT | 14113 | 4404 | -3963.75 | -3448.72 | -3521.7 |
| MATICUSDT | 3110 | 915 | -825.65 | -714.91 | -769.96 |
| SOLUSDT | 13180 | 3988 | -3619.75 | -3118.27 | -3208.35 |
| XRPUSDT | 13307 | 3663 | -3526.28 | -3132.08 | -3152.49 |

## M0 by global-context state at the candidate

| state | candidates | filled | M0 mean R / candidate |
|---|---|---|---|
| ALT_RISK_OFF | 36006 | 10393 | -0.2576 |
| ALT_RISK_ON | 27452 | 7675 | -0.2775 |
| BROAD_RISK_OFF | 16568 | 5029 | -0.2842 |
| BTC_LED_ALT_HEADWIND | 12 | 4 | 0.1562 |
| TRANSITION | 43524 | 13118 | -0.3175 |

Exit reasons: {'NO_TRIGGER': 59223, 'PRE_INVALIDATION': 28109, 'STOP': 25284, 'TARGET': 10897, 'TIME': 38, 'NONE': 11}

## Assumptions and deviations from live

- **data_quality**: candles_only (no historical order book / OI / CVD)
- **arm_latency_minutes**: 3.0
- **watched_pairs_in_m0_regime**: ['SOLUSDT']
- **fvg_zone**: absent (M0 does not use it)
- **breadth_universe**: point-in-time per quarter, top 20 by prior-month median daily quote volume, listed >= 730d, no Alpha-tag filter (no history)
- **costs**: live shadow cost model (plan_geometry)
- **overlap**: each candidate resolved independently; concurrent positions not netted

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
