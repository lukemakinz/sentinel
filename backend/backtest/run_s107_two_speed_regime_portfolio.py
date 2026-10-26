"""Frozen S107 replay: Book A plus full S102 or its ETH-short hedge only."""
import argparse
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from l1_filter.book_a_risk_overlay import BOOK_A_RISK_DEFAULT
from l1_filter.book_a_small_tsmom import BOOK_A_ALT_RM
from l1_filter.global_regime_trend_oi import (
    AsymmetricRegimeConfig,
    RegimeTrendOIConfig,
    asymmetric_global_regimes,
    weekly_regime_trend_oi_targets,
)
from .book_a_portfolio_sim import simulate_book_a
from .metrics_data import load_metrics
from .run_s100_global_regime_oi_swing import (
    _daily_open_interest,
    _daily_profit_factor,
    _direction_pnl,
    _target_counts,
)
from .run_s101_asymmetric_regime_trend_oi import (
    COSTS as S102_COSTS,
    OI_SYMBOLS,
    OI_WARMUP,
    PRICE_WARMUP,
    START as S102_START,
    SYMBOLS as S102_SYMBOLS,
)
from .run_s97_dual_horizon_trend import _monthly_dispersion
from .scalp_data import load_archives
from .swing_data import load_interval_archives
from .trend_carry_portfolio import simulate_trend_portfolio
from .two_speed_portfolio import merge_sleeve_daily, short_only_targets


PROTOCOL_SHA256 = '150d83fec934ce3b6494e9003ef741575ba42154f4b0ff12800e159ff833f2f8'
BOOK_A_SYMBOLS = (
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'BNBUSDT')
WARMUP, START, END = '2024-08-01', '2025-05-01', '2026-09-01'
SLICES = {
    'development': ('2025-05-01', '2025-10-01'),
    'former_validation_now_diagnostic': ('2025-10-01', '2026-04-01'),
    'former_evaluation_now_diagnostic': ('2026-04-01', END),
}
BOOK_A_COSTS = {
    'base': {'a': 7.0},
    'stress': {'a': 12.0},
    'severe': {'a': 20.0},
}
PARENT_PROTOCOLS = {
    'book_a': (
        'docs/research/book_ab_r5_a_cash/protocol.json',
        '2c284c1ba019d03483e2c42fb326d51c4662c15e11ca49434ce1c86e61798622',
    ),
    's102': (
        'docs/research/s102_eth_short_regime_router/protocol.json',
        'e97a9e5b495f52097215414c55ba0e0fd67c407f61f2ba026213e1e2e8e23094',
    ),
}
VARIANTS = ('book_a_cash', 'book_a_s102_full', 'book_a_s102_short_only')
CANDIDATES = VARIANTS[1:]


def _utc(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return (timestamp.tz_localize('UTC') if timestamp.tzinfo is None
            else timestamp.tz_convert('UTC'))


def _selected_targets(targets: list[dict], start=START, end=END) -> list[dict]:
    return [
        target for target in targets
        if _utc(start) <= _utc(target['timestamp']) < _utc(end)
    ]


def _slice_summary(full_daily: pd.Series, start, end,
                   initial: float = 500.0) -> dict:
    full_daily = full_daily.sort_index()
    start, end = _utc(start), _utc(end)
    before = full_daily.loc[full_daily.index < start]
    selected = full_daily.loc[
        (full_daily.index >= start) & (full_daily.index < end)]
    start_nav = initial + float(before.sum())
    full_equity = initial + full_daily.cumsum()
    running_peak = pd.concat([
        pd.Series([initial], index=[
            full_daily.index.min() - pd.Timedelta(days=1)]),
        full_equity,
    ]).cummax().iloc[1:]
    selected_equity = full_equity.reindex(selected.index)
    selected_peak = running_peak.reindex(selected.index)
    drawdown = 1.0 - selected_equity / selected_peak
    prior_equity = initial + full_daily.cumsum().shift(1).fillna(0.0)
    daily_return = selected / prior_equity.reindex(selected.index)
    tail_n = max(1, int(np.ceil(len(daily_return) * 0.05)))
    net = float(selected.sum())
    return {
        'start_nav': float(start_nav),
        'end_nav': float(start_nav + net),
        'net_pnl': net,
        'return_on_slice_start_pct': net / start_nav * 100 if start_nav else 0.0,
        'usd_per_calendar_day': net / max(1, (end - start).days),
        'max_continuous_drawdown_pct': (
            float(drawdown.max() * 100) if len(drawdown) else 0.0),
        'expected_shortfall_95_daily_return_pct': (
            float(daily_return.nsmallest(tail_n).mean() * 100)
            if len(daily_return) else 0.0),
        'positive_month_share': (
            float((selected.resample('ME').sum() > 0).mean())
            if len(selected) else 0.0),
    }


def _comparison(base: pd.Series, candidate: pd.Series, start, end,
                bootstrap: bool = False) -> dict:
    start, end = _utc(start), _utc(end)
    frame = pd.DataFrame({
        'base': base.loc[(base.index >= start) & (base.index < end)],
        'candidate': candidate.loc[
            (candidate.index >= start) & (candidate.index < end)],
    }).fillna(0.0)
    excess = frame['candidate'] - frame['base']
    result = {
        'excess_pnl': float(excess.sum()),
        'positive_excess_month_share': float(
            (excess.resample('ME').sum() > 0).mean()),
    }
    if bootstrap:
        result['paired_28d_bootstrap_95_lower_excess_pnl'] = (
            _block_bootstrap_lower(excess))
    return result


def _block_bootstrap_lower(excess: pd.Series, block: int = 28,
                           samples: int = 10_000, seed: int = 9404) -> float:
    values = excess.to_numpy(dtype=float)
    if not len(values):
        return 0.0
    rng = np.random.default_rng(seed)
    starts = np.arange(max(1, len(values) - block + 1))
    blocks_needed = int(np.ceil(len(values) / block))
    draws = np.empty(samples, dtype=float)
    for sample in range(samples):
        selected = np.concatenate([
            values[start:start + block]
            for start in rng.choice(starts, blocks_needed, replace=True)
        ])[:len(values)]
        draws[sample] = float(selected.sum())
    return float(np.quantile(draws, 0.025))


def _correlation(first: pd.Series, second: pd.Series) -> float:
    frame = pd.DataFrame({'first': first, 'second': second}).fillna(0.0)
    value = frame['first'].corr(frame['second'])
    return float(value) if np.isfinite(value) else 0.0


def _variant_summary(daily: pd.Series, sleeve_pnl: dict) -> dict:
    row = _slice_summary(daily, START, END, initial=500.0)
    row['daily_profit_factor'] = _daily_profit_factor(daily)
    row['usd_per_month'] = row['usd_per_calendar_day'] * 30.4375
    row.update(sleeve_pnl)
    return row


def _candidate_gate(result: dict, candidate: str) -> dict:
    control = 'book_a_cash'
    scenario_profit = {
        scenario: (
            result['full'][scenario][candidate]['net_pnl']
            > result['full'][scenario][control]['net_pnl']
        ) for scenario in ('base', 'stress', 'severe')
    }
    stress_candidate = result['full']['stress'][candidate]
    stress_control = result['full']['stress'][control]
    severe_candidate = result['full']['severe'][candidate]
    stress_comparison = result['comparisons']['stress'][candidate]
    stress_slices = {
        name: result['slice_comparisons'][name]['stress'][candidate]['excess_pnl']
        for name in SLICES
    }
    checks = {
        'beats_control_base_stress_severe': all(scenario_profit.values()),
        'stress_and_severe_pnl_positive': (
            stress_candidate['net_pnl'] > 0 and severe_candidate['net_pnl'] > 0),
        'stress_drawdown_within_1pp': (
            stress_candidate['max_continuous_drawdown_pct']
            <= stress_control['max_continuous_drawdown_pct'] + 1.0),
        'stress_es95_within_0_10pp': (
            stress_candidate['expected_shortfall_95_daily_return_pct']
            >= stress_control['expected_shortfall_95_daily_return_pct'] - 0.10),
        'stress_positive_excess_month_share_at_least_50pct': (
            stress_comparison['positive_excess_month_share'] >= 0.50),
        'paired_bootstrap_lower_above_zero': (
            stress_comparison['paired_28d_bootstrap_95_lower_excess_pnl'] > 0),
        'no_stress_slice_below_minus_2usd': min(stress_slices.values()) >= -2.0,
        'short_contribution_positive': result['stress_short_evidence']['net_pnl'] > 0,
        'at_least_five_short_decisions': (
            result['target_counts']['short_only']['short_decisions'] >= 5),
    }
    return {
        'passed': all(checks.values()),
        'checks': checks,
        'scenario_beats_control': scenario_profit,
        'stress_slice_excess_pnl': stress_slices,
    }


def _render_report(result: dict) -> str:
    lines = [
        '# S107 — two-speed regime portfolio', '',
        f'Protocol hash: `{result["protocol_sha256"]}`.', '',
        '**Historical portfolio-construction diagnostic; all shared history is '
        'selection-contaminated. Live remains disabled.**', '',
        'Control is $250 Book A + $250 cash. The two candidates replace only the '
        'cash reserve with the frozen S102 sleeve or its mechanical ETH-short-only filter.', '',
        '| Costs | Variant | PnL | $/month | DD | ES95 daily | PF |',
        '|---|---|---:|---:|---:|---:|---:|',
    ]
    for scenario in ('base', 'stress', 'severe'):
        for variant in VARIANTS:
            row = result['full'][scenario][variant]
            lines.append(
                f'| {scenario} | {variant} | ${row["net_pnl"]:.2f} | '
                f'${row["usd_per_month"]:.2f} | '
                f'{row["max_continuous_drawdown_pct"]:.2f}% | '
                f'{row["expected_shortfall_95_daily_return_pct"]:.3f}% | '
                f'{row["daily_profit_factor"]:.3f} |')
    lines.extend(['', '## Stress-cost time slices', '',
                  '| Slice | Control | Full S102 | Short-only | Full excess | Short excess |',
                  '|---|---:|---:|---:|---:|---:|'])
    for name in SLICES:
        rows = result['slices'][name]['stress']
        comparisons = result['slice_comparisons'][name]['stress']
        lines.append(
            f'| {name} | ${rows["book_a_cash"]["net_pnl"]:.2f} | '
            f'${rows["book_a_s102_full"]["net_pnl"]:.2f} | '
            f'${rows["book_a_s102_short_only"]["net_pnl"]:.2f} | '
            f'${comparisons["book_a_s102_full"]["excess_pnl"]:.2f} | '
            f'${comparisons["book_a_s102_short_only"]["excess_pnl"]:.2f} |')
    lines.extend(['', '## Frozen gate', ''])
    for candidate in CANDIDATES:
        gate = result['historical_gate'][candidate]
        failed = [name for name, passed in gate['checks'].items() if not passed]
        lines.append(
            f'- `{candidate}`: **{"PASS" if gate["passed"] else "FAIL"}**; '
            f'failed checks: `{failed}`.')
    lines.extend([
        '', f'S102 target audit in the shared window: `{result["target_counts"]}`.',
        f'Stress S102 direction PnL: `{result["stress_full_s102_direction_pnl"]}`.',
        f'Stress short-only evidence: `{result["stress_short_evidence"]}`.',
        f'Stress sleeve correlations: `{result["stress_sleeve_correlations"]}`.', '',
        f'**Decision: {result["decision"]}.**', '',
        'A historical pass would authorize a fresh paper-forward challenger only. '
        'It would not prove profitability and would not enable live trading.', '',
    ])
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minute-cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--daily-cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument('--output', default='docs/research/s107_two_speed_regime_portfolio')
    args = parser.parse_args()
    output = Path(args.output)
    protocol = output / 'protocol.json'
    actual_hash = sha256(protocol.read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError(f'Protocol changed after freeze: {actual_hash}')
    for name, (path, expected) in PARENT_PROTOCOLS.items():
        observed = sha256(Path(path).read_bytes()).hexdigest()
        if observed != expected:
            raise ValueError(f'{name} parent protocol changed: {observed}')
    (output / 'protocol.sha256').write_text(f'{actual_hash}  protocol.json\n')

    minutes, minute_manifest = {}, {}
    for symbol in BOOK_A_SYMBOLS:
        minutes[symbol], _, minute_manifest[symbol] = load_archives(
            symbol, WARMUP, END, args.minute_cache)
        print(symbol, len(minutes[symbol]), 'verified minute candles', flush=True)

    daily, funding, daily_manifest = {}, {}, {'prices': {}, 'metrics': {}}
    for symbol in S102_SYMBOLS:
        daily[symbol], funding[symbol], daily_manifest['prices'][symbol] = (
            load_interval_archives(
                symbol, PRICE_WARMUP, END, args.daily_cache, interval='1d'))
        print(symbol, len(daily[symbol]), 'verified daily candles', flush=True)
    open_interest = {}
    for symbol in OI_SYMBOLS:
        metrics, daily_manifest['metrics'][symbol] = load_metrics(
            symbol, OI_WARMUP, END, args.daily_cache,
            include_freshness=True, required_columns=('open_interest',))
        open_interest[symbol] = _daily_open_interest(metrics)
        print(symbol, len(open_interest[symbol]), 'verified daily OI closes', flush=True)
    (output / 'manifest.json').write_text(json.dumps({
        'book_a_minutes': minute_manifest,
        's102_daily': daily_manifest,
    }, indent=2) + '\n')

    regime_config = AsymmetricRegimeConfig()
    execution_config = RegimeTrendOIConfig()
    regimes = asymmetric_global_regimes(daily, S102_START, END, regime_config)
    full_targets = weekly_regime_trend_oi_targets(
        daily, funding, open_interest, regimes, S102_START, END,
        execution_config, symbol_order=S102_SYMBOLS, short_symbols=('ETHUSDT',))
    hedge_targets = short_only_targets(full_targets)
    selected_full_targets = _selected_targets(full_targets)
    selected_hedge_targets = _selected_targets(hedge_targets)
    markets = {symbol: (daily[symbol], funding[symbol]) for symbol in S102_SYMBOLS}

    result = {
        'protocol_sha256': actual_hash,
        'parent_protocol_sha256': {
            name: expected for name, (_, expected) in PARENT_PROTOCOLS.items()},
        'regime_config': asdict(regime_config),
        's102_execution_config': asdict(execution_config),
        'target_counts': {
            'full': _target_counts(selected_full_targets),
            'short_only': _target_counts(selected_hedge_targets),
        },
        'regime_occupancy': {
            str(key): float(value) for key, value in
            regimes.loc[(_utc(START) <= regimes.index) & (regimes.index < _utc(END)),
                        'regime'].value_counts(normalize=True).items()
        },
        'full': {},
        'comparisons': {},
        'slices': {},
        'slice_comparisons': {},
    }
    daily_outputs = {}
    replay_outputs = {}
    for scenario in ('base', 'stress', 'severe'):
        book_a = simulate_book_a(
            minutes, replace(
                BOOK_A_ALT_RM, taker_fee_bps=BOOK_A_COSTS[scenario]['a']),
            _utc(START), _utc(END), 250.0, risk=BOOK_A_RISK_DEFAULT)
        full_replay = simulate_trend_portfolio(
            markets, full_targets, START, END, 250.0, S102_COSTS[scenario])
        hedge_replay = simulate_trend_portfolio(
            markets, hedge_targets, START, END, 250.0, S102_COSTS[scenario])
        variant_daily = {
            'book_a_cash': book_a.daily_pnl,
            'book_a_s102_full': merge_sleeve_daily(
                book_a.daily_pnl, full_replay['daily_pnl']),
            'book_a_s102_short_only': merge_sleeve_daily(
                book_a.daily_pnl, hedge_replay['daily_pnl']),
        }
        replay_outputs[scenario] = {
            'book_a': book_a,
            's102_full': full_replay,
            's102_short_only': hedge_replay,
        }
        result['full'][scenario] = {
            'book_a_cash': _variant_summary(variant_daily['book_a_cash'], {
                'book_a_pnl': book_a.summary['net_pnl'], 'reserve_pnl': 0.0}),
            'book_a_s102_full': _variant_summary(
                variant_daily['book_a_s102_full'], {
                    'book_a_pnl': book_a.summary['net_pnl'],
                    's102_pnl': full_replay['summary']['net_pnl']}),
            'book_a_s102_short_only': _variant_summary(
                variant_daily['book_a_s102_short_only'], {
                    'book_a_pnl': book_a.summary['net_pnl'],
                    's102_pnl': hedge_replay['summary']['net_pnl']}),
        }
        result['comparisons'][scenario] = {
            candidate: _comparison(
                variant_daily['book_a_cash'], variant_daily[candidate],
                START, END, bootstrap=(scenario == 'stress'))
            for candidate in CANDIDATES
        }
        for name, bounds in SLICES.items():
            result['slices'].setdefault(name, {})[scenario] = {
                variant: _slice_summary(daily_series, *bounds, initial=500.0)
                for variant, daily_series in variant_daily.items()
            }
            result['slice_comparisons'].setdefault(name, {})[scenario] = {
                candidate: _comparison(
                    variant_daily['book_a_cash'], variant_daily[candidate], *bounds)
                for candidate in CANDIDATES
            }
        for variant, daily_series in variant_daily.items():
            daily_outputs[f'{scenario}_{variant}'] = daily_series
        print(scenario, {
            variant: round(row['net_pnl'], 4)
            for variant, row in result['full'][scenario].items()
        }, flush=True)

    stress_replays = replay_outputs['stress']
    result['stress_full_s102_direction_pnl'] = _direction_pnl(
        stress_replays['s102_full']['daily_pnl'], full_targets)
    result['stress_short_evidence'] = {
        'net_pnl': stress_replays['s102_short_only']['summary']['net_pnl'],
        'funding_pnl': stress_replays['s102_short_only']['summary']['funding_pnl'],
        'rebalances': stress_replays['s102_short_only']['summary']['rebalances'],
    }
    result['stress_sleeve_correlations'] = {
        'book_a_vs_s102_full': _correlation(
            stress_replays['book_a'].daily_pnl,
            stress_replays['s102_full']['daily_pnl']),
        'book_a_vs_s102_short_only': _correlation(
            stress_replays['book_a'].daily_pnl,
            stress_replays['s102_short_only']['daily_pnl']),
    }
    result['stress_monthly_dispersion'] = {
        variant: _monthly_dispersion(daily_outputs[f'stress_{variant}'])
        for variant in VARIANTS
    }
    result['historical_gate'] = {
        candidate: _candidate_gate(result, candidate) for candidate in CANDIDATES
    }
    passed = [
        candidate for candidate in CANDIDATES
        if result['historical_gate'][candidate]['passed']
    ]
    if passed:
        selected = sorted(
            passed,
            key=lambda candidate: (
                -result['full']['stress'][candidate]['net_pnl'],
                result['full']['stress'][candidate]['max_continuous_drawdown_pct'],
            ),
        )[0]
        result['decision'] = f'{selected.upper()}_PAPER_FORWARD_CHALLENGER_ONLY'
    else:
        selected = None
        result['decision'] = 'BOTH_CANDIDATES_REJECTED_AT_HISTORICAL_GATE'
    result['selected_candidate'] = selected
    result['paper_forward'] = {
        'minimum_calendar_days': 180,
        'minimum_s102_weekly_decisions': 26,
        'live_enabled': False,
    }

    pd.DataFrame(daily_outputs).to_csv(output / 'daily_pnl.csv', index_label='timestamp')
    regimes.to_csv(output / 'global_regimes.csv', index_label='decision_timestamp')
    (output / 'summary.json').write_text(
        json.dumps(result, indent=2, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_render_report(result))
    print(result['decision'], flush=True)


if __name__ == '__main__':
    main()
