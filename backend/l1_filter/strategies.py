"""Strategy definitions — gate requirements per strategy."""

STRATEGIES = {
    'S1': {
        'name':            'SMC Sweep Legacy',
        'description':     'Alias to S1A for backward compatibility',
        'alias_for':       'S1A',
    },
    'S1A': {
        'name':            'SMC Sweep',
        'description':     'NY reversal: liquidity sweep → CHoCH → FVG entry',
        'gates_a_all':     True,
        'gates_b_must':    ['B1', 'B2'],
        'gates_b_min':     2,
        'gates_c_must':    ['C1'],
        'gates_c_min':     2,
    },
    'S1B': {
        'name':            'SMC Continuation',
        'description':     'Continuation/retest: FVG + value + BOS/CHoCH confirmation',
        'gates_a_all':     True,
        'gates_b_must':    ['B2'],
        'gates_b_min':     2,
        'gates_c_must':    ['C1'],
        'gates_c_min':     2,
    },
    'S1C': {
        'name':            'SMC Reclaim',
        'description':     'Sweep -> reclaim -> retest with hybrid execution',
        'gates_a_all':     True,
        'gates_b_must':    ['B1', 'B2'],
        'gates_b_min':     2,
        'gates_c_must':    ['C1'],
        'gates_c_min':     2,
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
                         has_whale_cvd: bool = False,
                         ctx: dict | None = None) -> list[str]:
    """Return list of strategy IDs that pass with the given gate results."""
    if ctx and ctx.get('strategy_candidates'):
        candidates = list(ctx['strategy_candidates'])
        if 'S1A' in candidates and 'S1' not in candidates:
            candidates.append('S1')
        return candidates

    passing = []

    for strategy_id, cfg in STRATEGIES.items():
        if cfg.get('alias_for'):
            if cfg['alias_for'] in passing:
                passing.append(strategy_id)
            continue

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

    if 'S1A' in passing and 'S1' not in passing:
        passing.append('S1')
    return passing
