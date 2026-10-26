"""L2-EDGE final report: reads the checkpointed raw observation CSV from
run_l2_edge_audit.py (already 429-safe, already complete for all 18
symbol-days) and adds the pieces the frozen spec required but the first
pass didn't print: block bootstrap CI (blocked by day, not i.i.d. per-row,
since rows within a day are heavily time-correlated), leave-one-day-out,
leave-one-symbol-out, and concentration of the mean in the largest events.
No re-download, no re-parse -- pure analysis of already-collected data.

Primary cell per mechanism: horizon_s=5, latency_ms=250 (matches the
run_l2_edge_audit.py primary table). exec_bps is the executable
(real bid/ask) forward return; that is the only number this audit trusts.
"""
import numpy as np
import pandas as pd

CSV = '/tmp/sentinel-tick-cache/l2_edge_results.csv'
RNG = np.random.default_rng(42)
N_BOOT = 2000


def block_bootstrap_ci(day_groups, n_boot=N_BOOT):
    """Resample WHOLE DAYS with replacement (not individual rows) --
    rows inside a day share overlapping-window autocorrelation, so a
    naive per-row bootstrap would understate the true CI width."""
    days = list(day_groups.keys())
    means = []
    for _ in range(n_boot):
        sampled_days = RNG.choice(days, size=len(days), replace=True)
        pooled = np.concatenate([day_groups[d] for d in sampled_days])
        means.append(pooled.mean())
    means = np.array(means)
    return np.percentile(means, 2.5), np.percentile(means, 97.5)


def main():
    df = pd.read_csv(CSV)
    sub = df[(df.horizon_s == 5) & (df.latency_ms == 250)].copy()

    print('=' * 100)
    print('L2-EDGE FINAL REPORT -- h=5s, latency=250ms (primary cell)')
    print('=' * 100)

    for mech in ('L2A', 'L2B', 'L2C'):
        g = sub[sub.mechanism == mech]
        x = g.exec_bps.to_numpy()
        n = len(x)
        mean = x.mean()
        median = np.median(x)
        hit = (x > 0).mean()

        day_groups = {d: gg.exec_bps.to_numpy() for d, gg in g.groupby('day')}
        ci_lo, ci_hi = block_bootstrap_ci(day_groups)

        # leave-one-day-out
        loo_day = []
        for d in day_groups:
            rest = np.concatenate([v for k, v in day_groups.items() if k != d])
            loo_day.append((d, rest.mean()))

        # leave-one-symbol-out
        sym_groups = {s: gg.exec_bps.to_numpy() for s, gg in g.groupby('symbol')}
        loo_sym = []
        for s in sym_groups:
            rest = np.concatenate([v for k, v in sym_groups.items() if k != s])
            loo_sym.append((s, rest.mean()))

        # concentration: contribution of top 1%/5% |exec_bps| events to total mean
        order = np.argsort(-np.abs(x))
        top1pct_n = max(1, int(n * 0.01))
        top5pct_n = max(1, int(n * 0.05))
        total_sum = x.sum()
        top1_share = x[order[:top1pct_n]].sum() / total_sum if total_sum != 0 else float('nan')
        top5_share = x[order[:top5pct_n]].sum() / total_sum if total_sum != 0 else float('nan')

        print(f'\n--- {mech} ---')
        print(f'n={n}  mean={mean:.4f}bps  median={median:.4f}bps  hit_rate={hit*100:.1f}%')
        print(f'  bootstrap 95% CI (block-by-day, n_boot={N_BOOT}): [{ci_lo:.4f}, {ci_hi:.4f}]  '
              f'{"EXCLUDES 0" if ci_lo > 0 or ci_hi < 0 else "INCLUDES 0"}')
        print(f'  events/day: {n / len(day_groups):.0f}  (n_days={len(day_groups)})')
        print('  leave-one-day-out mean (should stay stable if not single-day-driven):')
        for d, m in sorted(loo_day):
            print(f'    excl {d}: mean={m:.4f}')
        print('  leave-one-symbol-out mean (should stay same-signed if not single-symbol-driven):')
        for s, m in sorted(loo_sym):
            print(f'    excl {s}: mean={m:.4f}')
        print(f'  concentration: top 1% events ({top1pct_n} rows) = {top1_share*100:.1f}% of total signed sum; '
              f'top 5% ({top5pct_n} rows) = {top5_share*100:.1f}% of total signed sum')

    print('\n' + '=' * 100)
    print('per-day breakdown, h=5s, latency=250ms')
    print('=' * 100)
    for mech in ('L2A', 'L2B', 'L2C'):
        g = sub[sub.mechanism == mech]
        print(f'\n{mech}:')
        for d, gg in g.groupby('day'):
            print(f'  {d}: n={len(gg):>6d} exec_mean={gg.exec_bps.mean():>7.3f} '
                  f'hit_rate={(gg.exec_bps>0).mean()*100:>5.1f}%')


if __name__ == '__main__':
    main()
