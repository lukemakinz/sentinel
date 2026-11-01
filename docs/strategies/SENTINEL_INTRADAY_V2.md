# SENTINEL Intraday v2 — frozen product and research contract

**Status:** research/shadow only. Live execution remains disabled.

## What “day trading” means here

SENTINEL Intraday may use 1h and 4h data to understand regime, but it does not
hold a directional trade as a swing position. The decision stack is:

- 4h/1h: directional regime and global risk context;
- 15m: setup and structural invalidation;
- 5m: confirmation;
- closed 1m: deterministic entry and management;
- maximum hold: four hours;
- every position is flattened before the UTC trading day changes;
- no averaging down, widening a stop, martingale or overnight directional risk.

The system is not required to trade every day. The research target is normally
0–3 portfolio entries per day across a liquid universe, not 0–3 entries per
symbol. A day with no qualified setup is a correct result.

## Economics gate before a candidate may be armed

The failed-auction M0 baseline is frozen as a rejected control. A new setup may
not inherit its uneconomic geometry. Before AI is called, deterministic code
must verify all of the following:

1. The structural stop is naturally between 0.40% and 1.25% of entry. A setup
   with a smaller stop is rejected; the stop is not widened just to pass.
2. Stress entry plus exit costs are no more than 0.25R.
3. The first executable liquidity target leaves at least 0.75R gross and a
   positive result after stress costs.
4. Total visible target space is at least 1.50R gross.
5. Entry is limit-first when a post-confirmation retest is available. An
   unfilled limit expires; the system does not chase it with an immediate
   market order.
6. Only liquid perpetuals with a fresh order book, trades, OI, funding and
   complete candles are eligible.

These thresholds are preregistered engineering constraints. Changing any of
them creates a new strategy ID and a new evaluation sample.

## Three strategy hypotheses — not a parameter grid

The next research cycle contains three structurally different hypotheses.
They must be implemented and reported separately.

### H1 — trend pullback continuation

- 4h and 1h direction aligned;
- 15m displacement followed by an orderly pullback into a supplied FVG/order
  block or prior breakout level;
- 5m higher-low/lower-high plus directional close;
- closed 1m retest/confirmation entry;
- veto when global context is strongly opposed.

### H2 — session expansion after compression

- London or New York liquid window;
- measurable 15m volatility compression before the session impulse;
- breakout with executed-volume/OI confirmation;
- no entry on the breakout candle; only a 5m/1m retest that preserves the
  broken level;
- pass if target liquidity is too close.

### H3 — range extreme failed auction

- only when 1h/4h are genuinely range-like rather than merely conflicting;
- sweep of a repeatedly tested 15m extreme;
- absorption/flow reversal and close back inside the auction;
- no trade during a global risk-off impulse or an expanding directional
  regime.

H3 is not the old M0 with a new label. It requires range classification,
executed-flow confirmation and the economics gate above.

## Frozen management policies

P0 remains a control: static structural stop and one 1.5R target.

### P1 — scale and protect

- at +0.75R: realize 50% with a resting limit;
- after that candle closes: move the remaining stop to the better of
  cost-adjusted breakeven and closed 1m structure;
- close the remaining 50% at +1.50R;
- time/EOD exit is a market exit with stress slippage.

### P2 — protect, scale and trail

- after a closed candle reaches +0.50R: reduce the next-candle worst-case stop
  from −1R to −0.50R;
- at +0.75R: realize 40% and move the remaining stop to cost-adjusted BE;
- at +1.25R: realize another 30% and lock at least +0.50R on the remainder;
- final 30% trails 0.50R behind maximum favorable excursion;
- every stop change is active from the next closed 1m candle, never
  retroactively inside the candle that created it.

For both policies, if stop and TP are touched in one 1m candle, stop is scored
first. Every partial pays its own fee. P1/P2 are counterfactual research arms;
they do not become execution defaults merely because they produce more green
exits.

The first full diagnostic on the rejected M0 entry stream (SOLUSDT,
2024-01-01–2026-10-01, 3,988 fills) also rejected both management variants:
P0 −0.9077R/trade, P1 −0.9283R and P2 −0.9522R. P1 had no detectable positive
uplift; P2 was significantly worse. This freezes P1/P2 for M0 and confirms
that Intraday v2 needs structurally different entries rather than another
exit-parameter search.

## What “TP should happen often” means

It is a measured diagnostic, not a promise. On the current rejected M0 sample
for BTC/ETH/SOL/AVAX, favorable excursion reached:

- 0.50R in 48.8% of filled trades;
- 0.75R in 42.3%;
- 1.00R in 37.1%;
- 1.50R in 29.9%.

Therefore P1/P2 place TP1 at 0.75R, but a policy is promoted only if its **net
expectancy after all costs** and drawdown improve on the same candidate cohort.
TP hit rate by itself is not an objective; a high TP rate with larger remaining
losses can still be unprofitable.

## Promotion gate

Each H×P combination is reported on a common cohort and must pass all gates:

- positive net expectancy after stress costs;
- block-bootstrap confidence interval above zero after correction for the
  number of tested hypotheses;
- no single year, direction or symbol responsible for the whole result;
- acceptable drawdown and portfolio overlap;
- at least 100 filled historical observations for diagnosis;
- then a new, untouched forward period with at least 100 filled trades and 90
  calendar days;
- only after that: paper/canary review by a human.

AI can explain a candidate and later diagnose errors. It cannot loosen the
economics gate, change a stop, invent a target or promote a policy.

## Research status — 2026-11-01

- H1 trend pullback v1 failed the development stress gate: 3 fills, PF 0.566.
- The final H1 confirmation-entry v2 also failed: 5 fills, PF 0.742. H1 is
  closed on the shared historical sample; there will be no v3 threshold tune.
- A separate user-proposed double-top/bottom experiment required a controlled
  second sweep, regular RSI divergence, a low-ADX range, neckline break and
  retest. It produced 5 development candidates across eight symbols, one
  base-cost fill that reached target (+1.186 net R), and zero stress-cost fills.
  It is rejected for insufficient frequency/economics and does not count as
  the contracted H3 because it did not use executed-flow absorption.
- H2 session expansion is next. The contracted H3 range failed auction remains
  a separate future test and must include flow/absorption as specified above.

## Wymienny silnik strategii

Każde H1/H2/H3 jest osobnym, wersjonowanym pluginem, a nie kolejną gałęzią
`if` w egzekucji. Plugin posiada detektor setupu, kontrakt danych i trigger;
wspólny silnik posiada jakość danych, ekonomię, ryzyko, P0/P1/P2, replay,
shadow i post-mortem. Aktywne pluginy wybiera
`AUCTION_ENABLED_STRATEGIES`; wyłączenie blokuje nowe plany bez niszczenia
historii ani otwartych planów. Pełny kontrakt i szablon:
`docs/architecture/STRATEGY_PLUGIN_ENGINE.md`.
