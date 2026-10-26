"""Offline chronological research for S11 monthly funding carry.

No network access is allowed.  ETH, SOL and BNB are evaluated because those
are the non-BTC assets with complete local one-minute/funding archives.
"""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path

import pandas as pd

from .funding_carry import FundingCarryConfig, FundingCarryCosts, simulate_monthly_carry
from .scalp_data import load_archives


SYMBOLS = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
WARMUP, END = '2025-07-01', '2026-09-01'
WINDOWS = {
    'development': ('2025-08-01', '2026-01-01'),
    'validation': ('2026-01-01', '2026-04-01'),
    'evaluation': ('2026-04-01', '2026-09-01'),
    'forward_combined': ('2026-01-01', '2026-09-01'),
    'all_available': ('2025-08-01', '2026-09-01'),
}


def _assert_offline_cache(cache: Path) -> None:
    months = pd.period_range(WARMUP, pd.Timestamp(END) - pd.Timedelta(minutes=1), freq='M')
    missing = []
    for symbol in SYMBOLS:
        for month in months:
            for path in (
                cache / 'klines' / symbol / '1m' / f'{symbol}-1m-{month}.zip',
                cache / 'fundingRate' / symbol / f'{symbol}-fundingRate-{month}.zip',
            ):
                if not path.exists() or not Path(f'{path}.CHECKSUM').exists():
                    missing.append(str(path))
    if missing:
        raise FileNotFoundError(
            'Offline mode: required verified archives are missing: ' + ', '.join(missing[:10]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-scalp-cache')
    parser.add_argument('--output', default='docs/research/s11_funding_carry')
    args = parser.parse_args()
    cache, output = Path(args.cache), Path(args.output)
    _assert_offline_cache(cache)
    output.mkdir(parents=True, exist_ok=True)

    data, rates, manifest = {}, {}, {}
    for symbol in SYMBOLS:
        minutes, funding, manifest[symbol] = load_archives(symbol, WARMUP, END, str(cache))
        data[symbol] = minutes[['open', 'high']]
        rates[symbol] = funding

    base = FundingCarryConfig()
    stress = replace(base, costs=FundingCarryCosts(
        spot_fee_bps=10.0,
        futures_fee_bps=5.0,
        spot_slippage_bps=5.0,
        futures_slippage_bps=5.0,
    ), switch_hurdle_bps=50.0)
    scenarios = {'base': base, 'stress': stress}
    results = {}
    for scenario, config in scenarios.items():
        results[scenario] = {}
        for label, (start, end) in WINDOWS.items():
            result = simulate_monthly_carry(
                data, rates, start, end, config, initial_capital=250.0)
            results[scenario][label] = result
            summary = result['summary']
            print(
                f'{scenario:6} {label:16} episodes={summary["episodes"]} '
                f'funding=${summary["gross_funding_pnl"]:.4f} '
                f'costs=${summary["costs"]:.4f} net=${summary["net_pnl"]:.4f} '
                f'return={summary["return_pct"]:.3f}%',
                flush=True,
            )

    protocol = {
        'status': 'chronological_research_not_live_ready',
        'strategy': asdict(base),
        'capital_usd': 250,
        'allocation': '$100 long spot + $100 isolated short-perpetual margin + $50 reserve',
        'leverage': '1x futures notional/margin; BTC is never traded',
        'decision_rule': (
            'At 00:01 UTC on the first day of each month, rank the completed prior-month '
            'funding sum. Enter the leader at >=10 bps; exit the held asset at <=0 bps; '
            'switch only after a full round-trip cost hurdle.'
        ),
        'causality': 'Every decision uses funding observations strictly before that UTC month.',
        'base_costs': asdict(base.costs),
        'stress_costs': asdict(stress.costs),
        'limitations': [
            'Perpetual minute price is a proxy for both spot and funding mark price.',
            'Spot/perpetual basis, transfer delays, outages, taxes and liquidation-engine details are absent.',
            'The hedge is exact by quantity, so directional price PnL cancels by construction.',
            'There are too few independent carry episodes to call the edge proven.',
        ],
        'promotion_rule': (
            'Freeze parameters and paper-forward for >=12 months or >=12 independent episodes; '
            'require positive net result under stress, no liquidation breach, and realized basis/cost '
            'tracking within the stress allowance.'
        ),
        'windows': WINDOWS,
    }
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'results.json').write_text(json.dumps(results, indent=2, default=str) + '\n')


if __name__ == '__main__':
    main()
