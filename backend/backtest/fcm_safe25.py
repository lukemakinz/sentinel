"""Frozen FCM_SAFE25 configuration and acceptance gates."""
from dataclasses import replace

from .funding_carry_v2 import FCMConfig, FCMCosts


INITIAL_CAPITAL = 250.0
REQUIRED_WINDOWS = ('development', 'validation', 'retrospective_evaluation')


def safe25_configs() -> dict[str, FCMConfig]:
    base = FCMConfig(
        name='FCM_SAFE25',
        spot_notional_usd=25.0,
        futures_margin_usd=200.0,
        reserve_usd=25.0,
        max_initial_futures_leverage=.15,
        force_monthly_reset=True,
        emergency_futures_equity_floor_usd=125.0,
        emergency_max_mark_leverage=.75,
        emergency_detection_delay_minutes=1,
        quantity_steps=(
            ('ETHUSDT', .001),
            ('SOLUSDT', .01),
            ('BNBUSDT', .01),
        ),
        minimum_futures_notionals=(
            ('ETHUSDT', 20.0),
            ('SOLUSDT', 5.0),
            ('BNBUSDT', 5.0),
        ),
    )
    stress = replace(base, name='FCM_SAFE25_STRESS', costs=FCMCosts(
        spot_fee_bps=10.0,
        futures_fee_bps=5.0,
        spot_slippage_bps=5.0,
        futures_slippage_bps=5.0,
    ))
    severe = replace(base, name='FCM_SAFE25_SEVERE', costs=FCMCosts(
        spot_fee_bps=10.0,
        futures_fee_bps=10.0,
        spot_slippage_bps=10.0,
        futures_slippage_bps=10.0,
    ))
    return {'base': base, 'stress': stress, 'severe': severe}


def concentration_metrics(replay: dict) -> dict:
    episodes = replay['episodes']
    positive = [episode for episode in episodes if episode['pnl'] > 0]
    gross_profit = sum(episode['pnl'] for episode in positive)
    by_symbol = {}
    for episode in positive:
        by_symbol[episode['symbol']] = (
            by_symbol.get(episode['symbol'], 0.0) + episode['pnl'])
    return {
        'gross_profit_usd': gross_profit,
        'positive_profit_by_symbol_usd': by_symbol,
        'top_symbol_gross_profit_share': (
            max(by_symbol.values()) / gross_profit
            if gross_profit and by_symbol else None),
        'top_episode_gross_profit_share': (
            max((episode['pnl'] for episode in positive), default=0.0) / gross_profit
            if gross_profit else None),
    }


def evaluate_safe25_gate(results: dict, leave_one_out: dict) -> dict:
    """Return every predeclared gate, not just the first failed condition."""
    checks = []

    def check(name, passed, observed, requirement):
        checks.append({
            'name': name,
            'passed': bool(passed),
            'observed': observed,
            'requirement': requirement,
        })

    stress = results['stress']
    for window in REQUIRED_WINDOWS:
        summary = stress[window]['summary']
        check(
            f'stress_positive_{window}', summary['net_pnl'] > 0,
            summary['net_pnl'], '> 0 USD',
        )
        check(
            f'minimum_episodes_{window}', summary['episodes'] >= 6,
            summary['episodes'], '>= 6',
        )

    combined = stress['all_available']['summary']
    check('stress_positive_all_available', combined['net_pnl'] > 0,
          combined['net_pnl'], '> 0 USD')
    check('minimum_episodes_all_available', combined['episodes'] >= 20,
          combined['episodes'], '>= 20')
    check('no_emergency_close', combined['emergency_closes'] == 0,
          combined['emergency_closes'], '== 0')
    check('no_unfilled_emergency_close',
          combined['unfilled_emergency_closes'] == 0,
          combined['unfilled_emergency_closes'], '== 0')
    check('no_modelled_collateral_exhaustion',
          combined['modelled_liquidation_breaches'] == 0,
          combined['modelled_liquidation_breaches'], '== 0')
    check('exit_ready_futures_equity_buffer',
          combined['min_exit_ready_futures_equity_usd'] >= 125.0,
          combined['min_exit_ready_futures_equity_usd'], '>= 125 USD')
    check('high_mark_leverage_cap',
          combined['max_high_mark_leverage'] <= .75,
          combined['max_high_mark_leverage'], '<= 0.75x')
    check('mtm_drawdown_cap', combined['max_mtm_drawdown_pct'] <= 2.0,
          combined['max_mtm_drawdown_pct'], '<= 2%')
    check('pathwise_free_cash', combined['min_free_cash_after_entry_usd'] >= 20.0,
          combined['min_free_cash_after_entry_usd'], '>= 20 USD')
    check('ledger_reconciled', combined['ledger_reconciled'],
          combined['ledger_reconciled'], 'true')

    severe_net = results['severe']['all_available']['summary']['net_pnl']
    check('severe_positive_all_available', severe_net > 0,
          severe_net, '> 0 USD at 80 bps round trip')

    for excluded, replay in sorted(leave_one_out.items()):
        net = replay['summary']['net_pnl']
        check(f'leave_{excluded}_out_positive', net > 0, net, '> 0 USD')

    concentration = concentration_metrics(stress['all_available'])
    top_symbol = concentration['top_symbol_gross_profit_share']
    top_episode = concentration['top_episode_gross_profit_share']
    check('top_symbol_concentration',
          top_symbol is not None and top_symbol <= .65,
          top_symbol, '<= 65% of gross profit')
    check('top_episode_concentration',
          top_episode is not None and top_episode <= .50,
          top_episode, '<= 50% of gross profit')

    passed = all(row['passed'] for row in checks)
    return {
        'decision': ('HISTORICAL_GATE_PASS_PAPER_FORWARD_ONLY'
                     if passed else 'REJECTED_BY_FROZEN_GATE'),
        'passed': passed,
        'checks': checks,
        'concentration': concentration,
    }
