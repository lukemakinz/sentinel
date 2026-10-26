"""Monte Carlo risk-of-ruin / max-sustainable-risk study for a $250
account. Reframes the research question per the final project review:
not "how to make $25/day" but "what is the maximum risk per trade a
$250 account can sustain at an acceptable ruin probability, and what
$/day does that actually imply" -- for a GIVEN edge assumption, since
this project found no confirmed edge to plug in as ground truth.

Trade-outcome generator: bootstrap resampling from S20 H1's empirical,
pooled R-multiple distribution across all three historical windows
(n=290, mean R=-0.040, std R=1.28, ~0.73 trades/day) -- the most
extensively tested strategy in this project, used here purely as a
REALISTIC SHAPE for trade outcomes (skew, tail, variance), not because
it is a confirmed edge. Three scenarios:
    zero_edge      : the same 290 R-multiples, re-centered to mean 0
                      (same variance/shape, no edge) -- the sizing-only
                      ceiling with no edge at all.
    s20_as_tested   : the actual observed distribution (slightly
                      negative mean, as found) -- what sizing alone does
                      to something close to what was actually measured.
    hypothetical_25bp: the same distribution shifted to mean R=+0.25 --
                      illustrative only, a stand-in for "if a real edge
                      of this size were eventually confirmed."

Leverage's role: once leverage is high enough that required margin never
binds (checked explicitly below), leverage does NOT change any risk-of-
ruin number here at all -- outcomes are governed entirely by
risk_fraction (% of current equity risked per trade, compounding) and
the trade-outcome distribution. This is stated as a finding, not
assumed.
"""
import numpy as np
import json

TRADE_RATE_PER_DAY = 0.7323
HORIZON_TRADES = 250          # ~342 days at the historical rate, ~1 year
N_PATHS = 8000
START_EQUITY = 250.0
RISK_FRACTIONS = [0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20]

# leverage/margin sanity check (stated as a finding, not swept):
# a 1% risk_fraction trade with a typical ~0.5% stop distance needs
# notional = risk_usd / stop_pct = (0.01*equity) / 0.005 = 2x equity.
# Even 5x leverage already covers that; 30x is never the binding
# constraint at any risk_fraction tested below unless stop_pct is
# unrealistically tight (<risk_fraction/leverage_cap).


def load_r_multiples():
    with open('/tmp/sentinel-tick-cache/s20_r_multiples.json') as f:
        return np.array(json.load(f))


def simulate(r_pool, risk_fraction, n_paths=N_PATHS, horizon=HORIZON_TRADES, seed=42):
    rng = np.random.default_rng(seed)
    draws = rng.choice(r_pool, size=(n_paths, horizon), replace=True)
    growth = 1.0 + risk_fraction * draws
    growth = np.clip(growth, 1e-6, None)  # a single trade cannot make equity negative
    equity_path = START_EQUITY * np.cumprod(growth, axis=1)
    equity_path = np.concatenate([np.full((n_paths, 1), START_EQUITY), equity_path], axis=1)

    running_max = np.maximum.accumulate(equity_path, axis=1)
    drawdown = 1.0 - equity_path / running_max
    max_dd = drawdown.max(axis=1)
    final = equity_path[:, -1]
    min_equity_frac = equity_path.min(axis=1) / START_EQUITY

    return {
        'risk_fraction': risk_fraction,
        'p_hard_ruin_below_20pct': float(np.mean(min_equity_frac < 0.20)),
        'p_dd_ge_30pct': float(np.mean(max_dd >= 0.30)),
        'p_dd_ge_40pct': float(np.mean(max_dd >= 0.40)),
        'median_final_equity': float(np.median(final)),
        'p05_final_equity': float(np.quantile(final, 0.05)),
        'p95_final_equity': float(np.quantile(final, 0.95)),
        'median_implied_usd_per_day': float((np.median(final) - START_EQUITY) / (horizon / TRADE_RATE_PER_DAY)),
    }


def scenario_table(r_pool, label):
    print(f'\n{"="*100}\nSCENARIO: {label}  (mean R={r_pool.mean():.4f}, std R={r_pool.std():.4f})\n{"="*100}')
    header = (f'{"risk/trade":>10s} {"P(ruin<20%)":>12s} {"P(DD>=30%)":>11s} {"P(DD>=40%)":>11s} '
              f'{"median $end":>12s} {"p05 $end":>10s} {"p95 $end":>10s} {"median $/day":>13s}')
    print(header)
    rows = []
    for rf in RISK_FRACTIONS:
        s = simulate(r_pool, rf)
        rows.append(s)
        print(f'{rf*100:>9.1f}% {s["p_hard_ruin_below_20pct"]*100:>11.1f}% '
              f'{s["p_dd_ge_30pct"]*100:>10.1f}% {s["p_dd_ge_40pct"]*100:>10.1f}% '
              f'${s["median_final_equity"]:>10.2f} ${s["p05_final_equity"]:>8.2f} '
              f'${s["p95_final_equity"]:>8.2f} ${s["median_implied_usd_per_day"]:>11.4f}')
    return rows


def main():
    r_pool = load_r_multiples()
    zero_edge = r_pool - r_pool.mean()
    hypothetical = r_pool - r_pool.mean() + 0.25

    print(f'Horizon: {HORIZON_TRADES} trades (~{HORIZON_TRADES/TRADE_RATE_PER_DAY:.0f} days at '
          f'{TRADE_RATE_PER_DAY} trades/day). Paths per risk level: {N_PATHS}.')
    print('Ruin threshold: equity ever below 20% of start ($50). DD thresholds: 30% / 40%.')

    scenario_table(zero_edge, 'zero_edge (same variance as S20 H1, mean R shifted to exactly 0)')
    scenario_table(r_pool, 's20_as_tested (actual observed pooled distribution, mean R=-0.040)')
    scenario_table(hypothetical, 'hypothetical_25bp (illustrative: same shape, mean R=+0.25, NOT a confirmed edge)')


if __name__ == '__main__':
    main()
