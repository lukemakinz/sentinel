# Sentinel Auction Intelligence v1

**Status:** implemented in shadow mode; execution is hard-locked.

The system is a market-state adjudicator, not an autonomous order generator.
It can return only `PASS`, `WAIT`, or `ARM`. A future deterministic trigger,
risk engine and execution gate remain responsible for any order lifecycle.

## Data contract

Every decision receives one immutable snapshot containing:

- BTC/ETH 4h context and replayable internal alt breadth;
- Global Context v1.3 from fresh, sufficiently warmed BTC/ETH trends,
  ETH-vs-BTC relative return and a frozen 20-alt breadth universe;
- deterministic Trend State v1 for 5m/15m/1h/4h/1d: direction, strength,
  structure, ATR-normalized EMA slope/separation and volatility percentile;
- open-interest change, funding, whale/retail CVD and executed liquidations;
- recent support/resistance and any fresh structural context from L1;
- top-20 order-book spread, USD depth and imbalance;
- Attention/Interest Oscillator v1;
- freshness, sufficiency and data-quality gates;
- a closed strategy and management-policy registry.

The ingester always collects BTCUSDT and ETHUSDT as global context even when
they are not tradable watchlist members. Binance futures feeds use separate
`/market` (candles, trades, mark price, liquidations) and `/public` (depth)
WebSocket sessions. Open interest is refreshed directly by the ingester every
five minutes, so local shadow collection does not silently depend on Celery.

Missing or stale 15m/1h/4h candles, order book, OI or whale CVD causes an
immediate deterministic `PASS` before an AI provider is called. OI requires
two observations separated by 4–15 minutes, whale CVD requires approximately
five minutes of continuous coverage, and BTC/ETH 4h context must also be fresh.
Breadth constituents require at least 50 closed bars and a 1h close no older
than two hours. TOTAL/TOTAL2/TOTAL3/TOTAL3ES/BTC.D remain explicit unavailable
slots until a licensed, replayable source is configured; they are never inferred.

## Strategy registry

Only these shadow hypotheses can be named:

- `SAI1_FAILED_AUCTION`
- `SAI1_IFVG_FLIP`
- `SAI1_TREND_RETEST`

None is approved for live or paper execution. `ARM` requires an existing
two-sided entry zone, a future trigger, an invalidation and a named management
policy. The entry zone must exactly match a zone supplied in the immutable
snapshot. The model cannot return `ENTER`, quantity or leverage.

## Prospective shadow protocol

Every valid `ARM` creates one `AuctionShadowPlan`. Geometry and scoring are
mechanical rather than supplied by the model:

- stop = selected structural zone plus a 0.15 ATR buffer (minimum 5 bps);
- entry = close of the first qualifying closed 1m confirmation candle plus
  adverse market slippage;
- target = 1.5R by default;
- failed auction requires a sweep through the zone and a close back across it;
- IFVG flip and trend retest require a touch plus directional close outside;
- a close beyond the structural stop before entry invalidates the plan without
  counting a fictitious loss;
- a candle touching stop and target is always scored stop-first;
- entry/exit fees and adverse market slippage are deducted from net R;
- expiry is not scored unless candle coverage reaches the end of the TTL.

The 1d state is derived only from complete UTC days containing all six closed
4h bars. Every trend field is learning/research context and carries no execution
authority.

The scheduler deduplicates decisions by symbol, closed 15m bar, mode and prompt
version. Repeated Celery runs therefore cannot buy extra AI opinions on the
same bar or inflate the research sample.

## Risk and execution defaults

- risk per trade: 0.20%;
- daily portfolio stop: 0.60%;
- weekly stop: 1.80%;
- maximum leverage: 5x;
- maximum simultaneous positions: 2;
- stop policy: `INITIAL_STOP_ONLY` unless a separate experiment promotes a
  structural or hybrid policy.

Two preregistered intraday counterfactuals now run on every complete
post-entry window without changing the canonical P0 outcome:

- P1 scales 50% at 0.75R, then protects the remainder at cost-adjusted
  breakeven or better closed-1m structure, with a final 1.5R target;
- P2 cuts risk after 0.5R, scales 40% at 0.75R and 30% at 1.25R, then trails
  the 30% runner by 0.5R.

Both are stop-first, fully costed, limited to four hours and flat before the
UTC day changes. They remain research policies, not execution defaults.

The paper engine charges entry and exit fees, adverse market slippage and
partial-exit costs. When both stop and target occur inside one candle without
tick ordering, the stop is assumed first.

## CLI

Deterministic snapshot and preflight:

```bash
env/bin/python backend/manage.py analyze_market BTCUSDT
```

AI shadow adjudication, if a supported provider key is configured:

```bash
env/bin/python backend/manage.py analyze_market BTCUSDT --ai
```

Do not persist the audit row:

```bash
env/bin/python backend/manage.py analyze_market BTCUSDT --ai --no-save
```

One deduplicated cycle for the entire watchlist, followed by plan resolution:

```bash
env/bin/python backend/manage.py run_auction_shadow --ai
```

Current evidence report:

```bash
env/bin/python backend/manage.py auction_shadow_report
```

Each mechanical geometry opens one candidate episode for four hours. Repeated
15m scans remain in the audit log but do not create extra outcome plans. The
same baseline outcome is paired prospectively across four policies:

- M0: frozen mechanical baseline;
- M1: M0 plus frozen 1h/4h/1d trend-conflict veto;
- M2: first valid AI verdict.
- M3: M0 plus the frozen Global Context v1.3 headwind veto.

M1/M2/M3 `PASS` or `WAIT` scores zero PnL on the complete common cohort.
Terminal no-trigger and pre-invalidation episodes remain in the denominator at
0R. M3 reports `DATA_INELIGIBLE` separately from `GLOBAL_HEADWIND_VETO` so a
missing feed cannot be credited as market intelligence. No selector creates a
second outcome plan. Entry TTL and post-trigger maximum hold are independent
(`AUCTION_SHADOW_MAX_HOLD_MINUTES`).

## Deterministic learning record

After a terminal plan has a complete original holding window,
`auction-postmortem-v3-intraday-management` records one immutable diagnosis,
entry-time Trend State and Global Context, MFE/MAE, cost drag and policy actions
M0/M1/M2/M3. It also replays four frozen
counterfactuals on the same 1m candles: market entry with 1R, 1.5R and 2R
targets, a post-confirmation maker limit at the trigger close that expires
after five minutes, and the frozen P1/P2 intraday policies. Every replay is net
of configured fees/slippage and uses the same conservative stop-first rule.

Diagnoses separate success, signal failure, entry quality, management giveback,
cost drag, lack of follow-through, intrabar path ambiguity, no trigger,
pre-invalidation and incomplete data. These labels are descriptive evidence.
They cannot change a strategy or select a target automatically.

Historical M0/M1/M3 replay is a retrospective diagnostic, not out-of-sample
evidence. Incomplete right-edge observation windows are excluded. A true OOS
period begins only after the policy/version is preregistered and frozen.

Celery Beat runs the watchlist cycle every five minutes and advances open plans
every minute. Set `AUCTION_SHADOW_AI_ENABLED=True` to permit scheduled model
calls. Execution remains hard-locked regardless of this setting.

## Promotion rule

An `ARM` is a research observation only. Promotion requires paired evaluation
against the same mechanical candidate stream, stress and severe costs,
walk-forward folds, block bootstrap, direction and symbol ablations, and a
fresh paper-forward period. At least 100 closed plans are required before even
starting statistical inference. Profit is not inferred from model confidence.
