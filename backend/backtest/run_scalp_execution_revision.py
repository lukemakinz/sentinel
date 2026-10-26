"""Second bounded revision: leverage, passive entry, and volatility breakouts."""
from dataclasses import replace
import sys

from l1_filter.scalp_strategy_v2 import RevisionConfig
from . import run_scalp_revision as research


def execution_variants():
    result = []
    for setup in ('absorption', 'exhaustion', 'breakout_retest'):
        for target in (3, 4):
            result.append(RevisionConfig(
                f'S7v3_{setup}_15m_limit_{target}R_20x', setup, minutes=15,
                target_r=target, exit_style='trail' if target == 4 else 'fixed',
                max_hold=360, entry_style='limit', leverage=20))
    for setup in ('channel_breakout', 'squeeze_breakout', 'range_sweep'):
        for minutes in (15, 60):
            for target in (3, 4):
                result.append(RevisionConfig(
                    f'S7v3_{setup}_{minutes}m_{target}R_20x', setup, minutes=minutes,
                    target_r=target, exit_style='trail' if target == 4 else 'fixed',
                    max_hold=720, entry_style='market', leverage=20))
    return result


if __name__ == '__main__':
    # Same selection, accounting and unused-period protocol as v2; separate
    # output retains all unsuccessful prior experiments instead of overwriting.
    research.revision_variants = execution_variants
    if '--output' not in sys.argv:
        sys.argv.extend(['--output', 'docs/research/s7_execution_revision'])
    research.main()
