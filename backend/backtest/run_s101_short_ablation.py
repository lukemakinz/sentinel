"""Post-hoc instrument ablation for S101's losing short sleeve."""
import argparse
import json
from pathlib import Path

from l1_filter.global_regime_trend_oi import (
    AsymmetricRegimeConfig, RegimeTrendOIConfig,
    asymmetric_global_regimes, weekly_regime_trend_oi_targets,
)
from .metrics_data import load_metrics
from .run_s100_global_regime_oi_swing import (
    _daily_open_interest, _direction_pnl, _target_counts,
)
from .run_s101_asymmetric_regime_trend_oi import (
    END, OI_SYMBOLS, OI_WARMUP, PRICE_WARMUP, START, SYMBOLS,
)
from .run_s97_dual_horizon_trend import _slice_metrics
from .swing_data import load_interval_archives
from .trend_carry_portfolio import TrendPortfolioCosts, simulate_trend_portfolio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-s97-cache')
    parser.add_argument(
        '--output',
        default='docs/research/s101_asymmetric_regime_trend_oi/short_ablation.json')
    args = parser.parse_args()
    daily, funding = {}, {}
    for symbol in SYMBOLS:
        daily[symbol], funding[symbol], _ = load_interval_archives(
            symbol, PRICE_WARMUP, END, args.cache, interval='1d')
    open_interest = {}
    for symbol in OI_SYMBOLS:
        metrics, _ = load_metrics(
            symbol, OI_WARMUP, END, args.cache,
            include_freshness=True, required_columns=('open_interest',))
        open_interest[symbol] = _daily_open_interest(metrics)
    regimes = asymmetric_global_regimes(
        daily, START, END, AsymmetricRegimeConfig())
    markets = {symbol: (daily[symbol], funding[symbol]) for symbol in SYMBOLS}
    variants = {
        'none': (), 'btc': ('BTCUSDT',), 'eth': ('ETHUSDT',),
        'sol': ('SOLUSDT',), 'btc_eth': ('BTCUSDT', 'ETHUSDT'),
        'btc_sol': ('BTCUSDT', 'SOLUSDT'),
        'eth_sol': ('ETHUSDT', 'SOLUSDT'), 'all': OI_SYMBOLS,
    }
    result = {
        'disclosure': 'Post-hoc ablation; explanatory only, never a promotion gate.',
        'variants': {},
    }
    for name, short_symbols in variants.items():
        targets = weekly_regime_trend_oi_targets(
            daily, funding, open_interest, regimes, START, END,
            RegimeTrendOIConfig(), symbol_order=SYMBOLS,
            short_symbols=short_symbols)
        replay = simulate_trend_portfolio(
            markets, targets, START, END, 500.0, TrendPortfolioCosts(8.0, 5.0))
        result['variants'][name] = {
            'target_counts': _target_counts(targets),
            'summary': replay['summary'],
            'direction_pnl': _direction_pnl(replay['daily_pnl'], targets),
            'direction_pnl_by_slice': {
                slice_name: _direction_pnl(
                    replay['daily_pnl'].loc[
                        (replay['daily_pnl'].index >= slice_start)
                        & (replay['daily_pnl'].index < slice_end)],
                    targets,
                )
                for slice_name, (slice_start, slice_end) in {
                    'development': ('2024-08-01', '2025-05-01'),
                    'validation': ('2025-05-01', '2026-01-01'),
                    'retrospective': ('2026-01-01', END),
                }.items()
            },
            'slices': {
                'development': _slice_metrics(
                    replay['daily_pnl'], '2024-08-01', '2025-05-01'),
                'validation': _slice_metrics(
                    replay['daily_pnl'], '2025-05-01', '2026-01-01'),
                'retrospective': _slice_metrics(
                    replay['daily_pnl'], '2026-01-01', END),
            },
        }
        print(name, result['variants'][name]['direction_pnl'], flush=True)
    path = Path(args.output)
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
