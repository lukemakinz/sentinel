# S35 — read-only audit of the single executed trade

This is a diagnostic audit of the already-recorded S35 result. It does not
change the frozen protocol, candidate set, baseline result or promotion
decision. Prices come from the checksum-pinned DOGEUSDT perpetual archive
already listed in `manifest.json`.

## Recorded trade

- Scenario used for the main audit: **stress**, 5 bps taker fee and 10 bps
  adverse slippage per side.
- Setup: DOGEUSDT short after funding settled at 2024-02-28 16:00 UTC.
- Entry: 2024-02-28 16:05 UTC; raw open `0.10002`, stress fill
  `0.09991998`.
- Frozen `R`: `0.0013422453313`; quantity: `322 DOGE`; entry notional:
  `$32.1742`.
- Stop: `0.10127`; target: `0.09724`; no cost-BE update occurred.
- Exit: stop during the 16:15–16:20 candle, recorded at 16:20 UTC.
- Stress result: **-$0.499723 (-1.0000R)**, including `$0.032408` fees.
  The same market path lost `$0.470387 (-0.9412R)` under base costs.

## Actual first three candles

| Candle UTC | OHLC | What happened |
|---|---|---|
| 16:05–16:10 | 0.10002 / 0.10018 / 0.09969 / 0.09971 | Initial short moved only `0.171R` favorably and `0.194R` adversely. Neither barrier was hit. |
| 16:10–16:15 | 0.09972 / 0.10108 / 0.09971 / 0.10094 | The favorable extreme did not improve; cumulative adverse excursion reached `0.864R`. |
| 16:15–16:20 | 0.10094 / 0.10474 / 0.10090 / 0.10426 | The 1R stop was crossed. The candle subsequently extended to `3.591R` adverse. |

The +1R favorable trigger required for cost-BE was never reached while the
trade was open, so the delayed stop logic had no influence on the loss.

## Full 180-minute path

`fav R` and `adv R` measure each candle's favorable and adverse extremes from
the stress entry fill. Rows after 16:20 are counterfactual path observation;
the real position had already closed.

| Bar UTC | O | H | L | C | fav R | adv R | cum MFE R | cum MAE R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 16:05 | 0.10002 | 0.10018 | 0.09969 | 0.09971 | 0.171 | 0.194 | 0.171 | 0.194 |
| 16:10 | 0.09972 | 0.10108 | 0.09971 | 0.10094 | 0.156 | 0.864 | 0.171 | 0.864 |
| 16:15 | 0.10094 | 0.10474 | 0.10090 | 0.10426 | 0.000 | 3.591 | 0.171 | 3.591 |
| 16:20 | 0.10426 | 0.10603 | 0.10355 | 0.10568 | 0.000 | 4.552 | 0.171 | 4.552 |
| 16:25 | 0.10569 | 0.10764 | 0.10468 | 0.10503 | 0.000 | 5.752 | 0.171 | 5.752 |
| 16:30 | 0.10503 | 0.10525 | 0.10378 | 0.10454 | 0.000 | 3.971 | 0.171 | 5.752 |
| 16:35 | 0.10453 | 0.10566 | 0.10438 | 0.10555 | 0.000 | 4.276 | 0.171 | 5.752 |
| 16:40 | 0.10555 | 0.10938 | 0.10555 | 0.10906 | 0.000 | 7.048 | 0.171 | 7.048 |
| 16:45 | 0.10905 | 0.11700 | 0.10905 | 0.11529 | 0.000 | 12.725 | 0.171 | 12.725 |
| 16:50 | 0.11530 | 0.11856 | 0.11368 | 0.11628 | 0.000 | 13.887 | 0.171 | 13.887 |
| 16:55 | 0.11628 | 0.11976 | 0.11610 | 0.11879 | 0.000 | 14.781 | 0.171 | 14.781 |
| 17:00 | 0.11878 | 0.12369 | 0.11712 | 0.12129 | 0.000 | 17.709 | 0.171 | 17.709 |
| 17:05 | 0.12128 | 0.12128 | 0.11648 | 0.11732 | 0.000 | 15.914 | 0.171 | 17.709 |
| 17:10 | 0.11732 | 0.11935 | 0.11624 | 0.11916 | 0.000 | 14.476 | 0.171 | 17.709 |
| 17:15 | 0.11915 | 0.11918 | 0.11648 | 0.11730 | 0.000 | 14.349 | 0.171 | 17.709 |
| 17:20 | 0.11730 | 0.11824 | 0.11387 | 0.11447 | 0.000 | 13.649 | 0.171 | 17.709 |
| 17:25 | 0.11444 | 0.11530 | 0.10617 | 0.11142 | 0.000 | 11.458 | 0.171 | 17.709 |
| 17:30 | 0.11141 | 0.11148 | 0.09772 | 0.10785 | 1.639 | 8.612 | 1.639 | 17.709 |
| 17:35 | 0.10783 | 0.10896 | 0.10513 | 0.10817 | 0.000 | 6.735 | 1.639 | 17.709 |
| 17:40 | 0.10815 | 0.11096 | 0.10685 | 0.11028 | 0.000 | 8.225 | 1.639 | 17.709 |
| 17:45 | 0.11029 | 0.11061 | 0.10857 | 0.11012 | 0.000 | 7.964 | 1.639 | 17.709 |
| 17:50 | 0.11011 | 0.11108 | 0.10840 | 0.10918 | 0.000 | 8.314 | 1.639 | 17.709 |
| 17:55 | 0.10917 | 0.11024 | 0.10883 | 0.10960 | 0.000 | 7.689 | 1.639 | 17.709 |
| 18:00 | 0.10962 | 0.11040 | 0.10785 | 0.10837 | 0.000 | 7.808 | 1.639 | 17.709 |
| 18:05 | 0.10835 | 0.10856 | 0.10651 | 0.10703 | 0.000 | 6.437 | 1.639 | 17.709 |
| 18:10 | 0.10702 | 0.10836 | 0.10600 | 0.10810 | 0.000 | 6.288 | 1.639 | 17.709 |
| 18:15 | 0.10810 | 0.10836 | 0.10633 | 0.10673 | 0.000 | 6.288 | 1.639 | 17.709 |
| 18:20 | 0.10673 | 0.10722 | 0.10150 | 0.10493 | 0.000 | 5.439 | 1.639 | 17.709 |
| 18:25 | 0.10493 | 0.10614 | 0.10353 | 0.10546 | 0.000 | 4.634 | 1.639 | 17.709 |
| 18:30 | 0.10546 | 0.10698 | 0.10533 | 0.10682 | 0.000 | 5.260 | 1.639 | 17.709 |
| 18:35 | 0.10682 | 0.10704 | 0.10564 | 0.10599 | 0.000 | 5.305 | 1.639 | 17.709 |
| 18:40 | 0.10599 | 0.10760 | 0.10599 | 0.10713 | 0.000 | 5.722 | 1.639 | 17.709 |
| 18:45 | 0.10714 | 0.10981 | 0.10707 | 0.10928 | 0.000 | 7.368 | 1.639 | 17.709 |
| 18:50 | 0.10928 | 0.10940 | 0.10756 | 0.10851 | 0.000 | 7.063 | 1.639 | 17.709 |
| 18:55 | 0.10854 | 0.11013 | 0.10845 | 0.10924 | 0.000 | 7.607 | 1.639 | 17.709 |
| 19:00 | 0.10923 | 0.11107 | 0.10922 | 0.11016 | 0.000 | 8.307 | 1.639 | 17.709 |

- Full-horizon MFE: **1.639R**, low `0.09772` in the 17:30–17:35 bar,
  85–90 minutes after entry.
- Full-horizon MAE: **17.709R**, high `0.12369` in the 17:00–17:05 bar,
  55–60 minutes after entry.
- The maximum adverse excursion occurred before the eventual favorable low.
- A barrier-free time exit at the 19:05 open (`0.11017`) would have lost
  **$3.3698** after stress costs.

## Frozen-entry counterfactual grid

The grid fixes the recorded stress entry, `R`, quantity and costs. Stops and
targets alone change. Stop/target prices are rounded adversely to the DOGE
tick, gaps use the worse price, and stop wins an ambiguous candle. Values show
net PnL and exit time. This is attribution, not a parameter search.

| Stop \ Target | 0.5R | 0.75R | 1R | 1.5R | 2R |
|---:|---:|---:|---:|---:|---:|
| 0.5R (`0.10060`) | -$0.2837, stop 16:15 | -$0.2837, stop 16:15 | -$0.2837, stop 16:15 | -$0.2837, stop 16:15 | -$0.2837, stop 16:15 |
| 0.75R (`0.10093`) | -$0.3901, stop 16:15 | -$0.3901, stop 16:15 | -$0.3901, stop 16:15 | -$0.3901, stop 16:15 | -$0.3901, stop 16:15 |
| 1R (`0.10127`) | -$0.4997, stop 16:20 | -$0.4997, stop 16:20 | -$0.4997, stop 16:20 | -$0.4997, stop 16:20 | -$0.4997, stop 16:20 |
| 1.25R (`0.10160`) | -$0.6061, stop 16:20 | -$0.6061, stop 16:20 | -$0.6061, stop 16:20 | -$0.6061, stop 16:20 | -$0.6061, stop 16:20 |
| 1.5R (`0.10194`) | -$0.7158, stop 16:20 | -$0.7158, stop 16:20 | -$0.7158, stop 16:20 | -$0.7158, stop 16:20 | -$0.7158, stop 16:20 |

Every tested stop was reached before every tested target. Widening the stop to
1.25R or 1.5R also breaches the original `$0.50` per-trade risk budget because
quantity was deliberately held fixed for attribution.

For diagnosis only, removing the stop entirely would produce the following:

| Target | First exit | Stress net PnL | Path cost before target |
|---:|---:|---:|---:|
| 0.5R | 17:35 | +$0.1517 | survived 17.709R MAE first |
| 0.75R | 17:35 | +$0.2581 | survived 17.709R MAE first |
| 1R | 17:35 | +$0.3678 | survived 17.709R MAE first |
| 1.5R | 17:35 | +$0.5838 | survived 17.709R MAE first |
| 2R | no hit; time 19:05 | -$3.3698 | 17.709R MAE and 7.636R adverse at time exit |

The no-stop rows are not admissible strategies: surviving `17.709R` would
discard the frozen risk limit and turn a `$0.50` planned loss into multi-dollar
tail exposure.

## Attribution

1. **Not a merely too-narrow stop.** Every stop from 0.5R through 1.5R failed.
   Reaching the later favorable move would have required tolerating more than
   17.709R adverse excursion, which is incompatible with the risk protocol.
2. **The 2R target was high, but it did not cause the recorded loss.** Even a
   0.5R target was not touched before any tested stop. A 1.5R target appeared
   only much later, after the extreme adverse squeeze.
3. **Primary cause: bad entry / false reversal confirmation.** The confirmation
   bar reversed by only `-0.1996%`; the first entry candle delivered just
   `0.171R` MFE, then the original upward impulse resumed. The short was on the
   wrong side of an immediate continuation squeeze.

This is one observation, so it supports causal attribution but not a protocol
mutation. Adding filters or changing barriers from this case alone would be
post-result overfitting.
