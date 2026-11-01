# S36 regime switch — DEVELOPMENT-only signal funnel

## Scope and safeguards

- This is a count-only exploration of the frozen S35 public, checksum-verified Binance inputs.
- Only the development interval `2022-01-01 <= T < 2023-07-01` was loaded, plus the earlier warm-up needed for causal rolling statistics. No validation or retrospective-evaluation outcome was loaded or inspected.
- No PnL, stop, target or future-return outcome was calculated.
- Each event needs its own symbol's 180 earlier funding observations and finite 60-minute event returns for the current event and the complete preceding 180-event window.
- The 60-minute move ends on the last complete pre-settlement bar (`T-5m`) and must have the same sign as funding.
- Premium is the completed `mark/index - 1` observation at `T-5m`; it must have the same sign as funding.
- `obs3` and `obs6` mean that, after all preceding filters, respectively 3 or 6 consecutive post-settlement 5-minute bars exist in **all three** price streams (perpetual, mark and index). Missing bars are not filled.

## Eight predeclared threshold combinations

The table is a cumulative funnel. Funding notation such as `3 bp / Q90` means
`abs(funding[T]) >= max(0.0003, trailing Q90(abs(funding)))`. Move quantiles use
the absolute 60-minute returns at the preceding 180 funding events and exclude
the event being classified.

| ID | Funding | Same-sign 60m move | Same-sign premium | Eligible | Funding | Move | Premium | obs3 | obs6 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 3 bp / Q90 | Q70 | 2.0 bp | 6,049 | 126 | 29 | 29 | 29 | 29 |
| B | 3 bp / Q90 | Q65 | 2.0 bp | 6,049 | 126 | 30 | 30 | 30 | 30 |
| C | 3 bp / Q90 | Q70 | 1.5 bp | 6,049 | 126 | 29 | 29 | 29 | 29 |
| D | 3 bp / Q90 | Q65 | 1.5 bp | 6,049 | 126 | 30 | 30 | 30 | 30 |
| E | 2 bp / Q85 | Q70 | 2.0 bp | 6,049 | 277 | 68 | 66 | 66 | 66 |
| F | 2 bp / Q85 | Q65 | 2.0 bp | 6,049 | 277 | 73 | 71 | 71 | 71 |
| G | 2 bp / Q85 | Q70 | 1.5 bp | 6,049 | 277 | 68 | 66 | 66 | 66 |
| H | 2 bp / Q85 | Q65 | 1.5 bp | 6,049 | 277 | 73 | 71 | 71 | 71 |

Lowering the premium floor from 2.0 bp to 1.5 bp adds no event after the
same-sign funding and move tests. Lowering only the move threshold from Q70 to
Q65 adds one event under strict funding and five events under broad funding.
The material increase comes from changing the funding definition from
`max(3 bp, Q90)` to `max(2 bp, Q85)`.

## Recommended minimum relaxation: E

Variant E is the smallest tested relaxation from A that yields at least 40
development observations before the future regime classifier. It changes only
the funding gate and retains the more selective Q70 move and 2.0 bp premium
requirements.

| Symbol | Eligible | Funding | Move | Premium | obs3 | obs6 | Positive funding | Negative funding |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SUIUSDT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| DOGEUSDT | 1,638 | 65 | 17 | 16 | 16 | 16 | 3 | 13 |
| XRPUSDT | 1,349 | 67 | 12 | 11 | 11 | 11 | 0 | 11 |
| SOLUSDT | 1,424 | 106 | 28 | 28 | 28 | 28 | 0 | 28 |
| ETHUSDT | 1,638 | 39 | 11 | 11 | 11 | 11 | 0 | 11 |
| **Total** | **6,049** | **277** | **68** | **66** | **66** | **66** | **3** | **63** |

SUI launched too late to accumulate 180 earlier funding observations before
the development cutoff, so its zero is structural rather than a failed signal.
All 66 qualified observations have complete 3- and 6-bar post-event data.

## Research decision

Use **E** as the frozen upstream event gate for the first S36 classifier test.
Do not loosen the premium threshold: it provided no additional development
sample. Do not loosen the move threshold initially: Q65 buys only five extra
events after broad funding, while increasing the risk of weak momentum inputs.

The sample is still sparse: 66 raw observations over 546 calendar days, or
about 0.121 events/day before portfolio collisions and before either the fade or
continuation confirmation. It is also directionally imbalanced (63 negative-
funding versus 3 positive-funding observations). Consequently this funnel is
large enough for a first deterministic regime-classification experiment, but
not large or balanced enough to support an AI execution role or to serve as the
sole engine for a high-frequency daily-income target.
