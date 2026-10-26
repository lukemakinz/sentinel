# Sentinel Auction Intelligence v1

**Status:** implemented in shadow mode; execution is hard-locked.

The system is a market-state adjudicator, not an autonomous order generator.
It can return only `PASS`, `WAIT`, or `ARM`. A future deterministic trigger,
risk engine and execution gate remain responsible for any order lifecycle.

## Data contract

Every decision receives one immutable snapshot containing:

- BTC/ETH 4h context and replayable internal alt breadth;
- 15m/1h/4h trend, ATR, volume surprise and OBV change;
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

Celery Beat runs the watchlist cycle every five minutes and advances open plans
every minute. Set `AUCTION_SHADOW_AI_ENABLED=True` to permit scheduled model
calls. Execution remains hard-locked regardless of this setting.

## Promotion rule

An `ARM` is a research observation only. Promotion requires paired evaluation
against the same mechanical candidate stream, stress and severe costs,
walk-forward folds, block bootstrap, direction and symbol ablations, and a
fresh paper-forward period. At least 100 closed plans are required before even
starting statistical inference. Profit is not inferred from model confidence.
