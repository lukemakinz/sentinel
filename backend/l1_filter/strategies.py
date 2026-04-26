"""Strategy definitions — gate requirements per strategy."""

STRATEGIES = {
    'S1': {
        'name':            'SMC Sweep',
        'description':     'Liquidity sweep → ChoCH → FVG entry',
        'gates_a_all':     True,
        'gates_b_must':    ['B1', 'B2'],  # sweep + FVG = core ICT setup
        'gates_b_min':     2,             # B1+B2 sufficient (optional: B3/B5 for higher conviction)
        'gates_c_must':    ['C1'],        # CHoCH is the trigger
        'gates_c_min':     1,             # CHoCH alone confirms reversal
    },
    'S2': {
        'name':            'Order Flow',
        'description':     'Whale CVD divergence + OI + funding',
        'gates_a_all':     False,
        'gates_a_must':    ['A1', 'A4', 'A5'],      # killzone + funding + ADX
        'gates_b_must':    [],
        'gates_b_min':     2,
        'gates_c_must':    [],
        'gates_c_min':     1,
        'whale_cvd_required': True,                  # needs WhaleCVD data
    },
    'S3': {
        'name':            'Classic TA',
        'description':     'EMA crossover + RSI + S/R level',
        'gates_a_all':     False,
        'gates_a_must':    ['A1', 'A2'],             # killzone + HTF trend
        'gates_b_must':    ['B3'],                   # premium/discount as S/R
        'gates_b_min':     2,
        'gates_c_must':    ['C2', 'C3'],             # RSI divergence + EMA align
        'gates_c_min':     2,
    },
}


def evaluate_strategies(gates_a: dict, gates_b: dict, gates_c: dict,
                         has_whale_cvd: bool = False) -> list[str]:
    """Return list of strategy IDs that pass with the given gate results."""
    passing = []

    for strategy_id, cfg in STRATEGIES.items():

        # Gate A check
        if cfg.get('gates_a_all'):
            if not all(gates_a.values()):
                continue
        else:
            must_a = cfg.get('gates_a_must', [])
            if not all(gates_a.get(g, False) for g in must_a):
                continue

        # Gate B check
        must_b = cfg.get('gates_b_must', [])
        if not all(gates_b.get(g, False) for g in must_b):
            continue
        b_count = sum(1 for v in gates_b.values() if v)
        if b_count < cfg['gates_b_min']:
            continue

        # Gate C check
        must_c = cfg.get('gates_c_must', [])
        if not all(gates_c.get(g, False) for g in must_c):
            continue
        c_count = sum(1 for v in gates_c.values() if v)
        if c_count < cfg['gates_c_min']:
            continue

        # S2 extra: needs Whale CVD data
        if cfg.get('whale_cvd_required') and not has_whale_cvd:
            continue

        passing.append(strategy_id)

    return passing
