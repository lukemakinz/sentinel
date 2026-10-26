"""Sequential S7 setups and oscillator ablations, not fitted probability claims."""
import sys

from l1_filter.price_action_scalp import action_features, action_signals, action_variants
from . import run_scalp_revision as research


if __name__ == '__main__':
    research.revision_variants = action_variants
    research.revision_features = action_features
    research.revision_signals = action_signals
    if '--output' not in sys.argv:
        sys.argv.extend(['--output', 'docs/research/s7_price_action'])
    if '--warmup-start' not in sys.argv:
        sys.argv.extend(['--warmup-start', '2025-11-20'])
    research.main()
