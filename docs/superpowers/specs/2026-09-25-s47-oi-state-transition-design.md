# S47 OI State Transition — design

Date frozen: 2026-09-25

## Purpose

S47 tests one falsifiable mechanism on free Binance USD-M data:

1. price sweeps known higher-timeframe liquidity in the direction opposite
   the established 4h structure;
2. open interest falls during the sweep, consistent with deleveraging;
3. price changes 15m structure back into the 4h trend;
4. open interest rebuilds after that change, consistent with new positions
   entering in the trend direction.

The goal is evidence of positive out-of-sample expectancy after realistic
costs. The design does not promise a daily dollar return. Leverage is a margin
tool and cannot turn a non-positive signal into an edge.

## Scope

- Traded universe: SOLUSDT, XRPUSDT, DOGEUSDT, ETHUSDT, BNBUSDT.
- BTCUSDT is a benchmark only and is never traded.
- Capital: one shared USD 250 account.
- At most one pending order or open position globally.
- Data: free Binance public 1m USD-M klines/funding and 5m metrics archives.
- Historical endpoint: 2026-08-31 inclusive.
- All historical results are `discovery-affected`; they can reject S47 or
  advance it to forward observation, but cannot authorize live trading.

## Causal signal

All bar timestamps denote the time at which a fully closed bar becomes known.
An order produced at timestamp `T` can first execute at the 1m open at `T`.

### 4h regime

Use confirmed width-two pivots. A pivot at bar `i` becomes known only after
bar `i + 2` closes.

- Bullish: the two latest confirmed highs and lows are each rising.
- Bearish: the two latest confirmed highs and lows are each falling.
- Otherwise: neutral and no setup is allowed.

### 1h liquidity level and sweep

In a bullish regime, monitor the latest confirmed 1h swing low. A bullish
sweep requires a 15m low at least 0.10 ATR(1h) below that level and a 15m
close back above it. The bearish rule is symmetric around the latest
confirmed 1h swing high.

Only one active setup may exist for a symbol and liquidity level. A level
cannot generate another setup after it has been consumed.

### OI reset

At the sweep close, compare the current 5m OI snapshot with OI at the start of
the 15m sweep bar. The snapshot must be no older than 10 minutes.

The reset is valid when OI falls by at least the larger of:

- 0.20%; or
- the trailing 30-day 70th percentile of absolute 15m OI changes, calculated
  strictly from observations available before the sweep.

The same reset rule applies to bullish and bearish sweeps because it identifies
position closure rather than direction.

### MSS, displacement, flow and rebuild

The setup expires after four subsequent closed 15m bars.

For a bullish setup, a confirmation bar must:

- close above the latest confirmed 15m swing high known before the sweep;
- have a body of at least 0.80 ATR(15m);
- close in the upper 25% of its range;
- have taker-buy volume greater than taker-sell volume.

Bearish confirmation is symmetric.

After confirmation, current OI must have recovered at least 50% of the reset
amount while remaining based on a snapshot no older than 10 minutes.
Confirmation and rebuild may occur on the same closed bar.

### Entry and exits

- Entry: market at the next available 1m open after confirmation.
- Stop: sweep extreme plus a 0.15 ATR(1h) adverse buffer.
- Initial target: 2.5R, capped at the nearest opposing confirmed 1h swing that
  was known at entry.
- Reject a setup whose capped target is below 1.5R or below three times the
  estimated all-in base cost.
- Time stop: four hours after entry.
- No partial exit, trailing stop, breakeven move or re-entry.
- Funding is charged from the historical funding series.

## Execution and risk

Historical signal evaluation uses:

- risk per trade: `min(0.20% of current equity, USD 0.50)`;
- leverage: 5x;
- maximum notional: 50% of equity;
- maximum margin: 10% of equity;
- daily loss limit: 0.60%;
- weekly loss limit: 1.80%;
- drawdown size reduction and halt already enforced by the shared cluster
  simulator.

Cost scenarios, per side:

- base: 5 bps taker fee + 2 bps adverse slippage;
- stress: 8 bps taker fee + 5 bps adverse slippage;
- severe: 10 bps taker fee + 10 bps adverse slippage.

No maker fills are claimed.

## Data integrity

- Every archive is recorded with URL, SHA-256 and row count.
- Missing 1m bars invalidate the affected execution period.
- Metrics remain on their native 5m grid.
- Forward-filled metrics expose the age of the last true observation.
- A setup is rejected when OI age exceeds 10 minutes.
- No interpolation across leading gaps is allowed.

## Historical evaluation

Use six synchronized chronological outer folds with the same boundaries for
all symbols. Use a 24-hour purge/embargo around fold boundaries. Rolling
thresholds use only data before each event.

Primary metrics:

- stress mean net R;
- stress profit factor;
- 95% weekly block-bootstrap interval for mean net R.

Required diagnostics:

- base, stress and severe results;
- result per fold, symbol and month;
- leave-one-symbol-out;
- largest symbol and month gross-profit concentration;
- break-even all-in round-trip cost;
- Deflated Sharpe Probability using a fixed prior-trial count of 48.

Historical `PASS_TO_FORWARD` requires all of:

1. at least 100 fills;
2. stress profit factor greater than 1.10;
3. positive stress mean net R;
4. lower 95% weekly block-bootstrap bound above zero;
5. Deflated Sharpe Probability at least 95%;
6. positive stress PnL in at least 70% of folds;
7. positive aggregate stress PnL after removing each symbol in turn;
8. no symbol or month contributes more than 40% of gross profit;
9. break-even cost at least 1.5 times stress cost.

Failure of any condition ends S47 without changing thresholds.

## Forward gate and sizing

If and only if the historical gate passes, freeze the implementation and begin
paper-forward observation from the next complete UTC day. There is no early
GO. The final decision waits for both at least 180 calendar days and at least
100 paper fills. The historical gate criteria apply unchanged.

Sizing is a separate future experiment. It may begin only after forward GO.
The approved policy is:

- maximum peak-to-trough drawdown: 30%;
- ruin: equity at or below 50% of starting equity;
- maximum 12-month probability of ruin: 5%;
- Kelly cap: 0.25 Kelly.

Only that later study may consider 10–20x leverage, and only as a margin cap.

## Non-goals

- no optimization or parameter grid;
- no selection of a winning subset of symbols after results;
- no L2, cross-venue, liquidation-print or queue assumptions;
- no live-executor integration;
- no claim that SMC/ICT labels create information beyond the measured OI
  transition;
- no fixed USD 20–25 daily withdrawal target.
