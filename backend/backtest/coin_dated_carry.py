"""Inverse COIN-M fixed-expiry cash-and-carry replay for S34."""
from dataclasses import asdict, dataclass
import math

import numpy as np
import pandas as pd

from backtest.dated_carry import _utc, _validate_hourly, quarterly_expiries


CONTRACT_SIZE_USD = {'BTCUSDT': 100.0, 'ETHUSDT': 10.0}


@dataclass(frozen=True)
class CoinCarryCosts:
    spot_fee_bps: float = 10.0
    futures_fee_bps: float = 2.0
    spot_slippage_bps: float = 1.0
    futures_slippage_bps: float = 1.0

    @property
    def headline_four_fill_rate_sum_bps(self):
        return 2 * (self.spot_fee_bps + self.futures_fee_bps
                    + self.spot_slippage_bps + self.futures_slippage_bps)


@dataclass(frozen=True)
class CoinCarryConfig:
    name: str = 'S34_coin_m_dated_carry'
    coin_purchase_usd: float = 225.0
    outside_reserve_usd: float = 25.0
    days_before_expiry: int = 30
    execution_delay_hours: int = 1
    exit_hours_before_expiry: int = 1
    minimum_premium_bps: float = 100.0
    minimum_annualized_premium_pct: float = 12.0
    maximum_unhedged_coin_fraction: float = .12
    minimum_collateral_equity_usd: float = 150.0
    maximum_futures_mark_leverage: float = 1.10
    costs: CoinCarryCosts = CoinCarryCosts()

    def validate(self, initial_capital=250.0):
        if self.coin_purchase_usd + self.outside_reserve_usd > initial_capital:
            raise ValueError('COIN-M carry allocation exceeds capital')
        if min(self.coin_purchase_usd, self.outside_reserve_usd) <= 0:
            raise ValueError('COIN-M carry allocations must be positive')
        if not 0 <= self.maximum_unhedged_coin_fraction < 1:
            raise ValueError('Invalid residual-coin cap')
        if self.maximum_futures_mark_leverage <= 0:
            raise ValueError('Invalid leverage cap')


def _contract_notional(symbol, coin_quantity, futures_price):
    size = CONTRACT_SIZE_USD[symbol]
    return math.floor(coin_quantity * futures_price / size) * size


def build_coin_carry_schedule(data, start, end, config):
    start, end = _utc(start), _utc(end)
    schedule = []
    for expiry in quarterly_expiries(start, end):
        decision = expiry - pd.Timedelta(days=config.days_before_expiry)
        if decision < start:
            continue
        cutoff = decision - pd.Timedelta(hours=1)
        candidates = []
        for symbol in sorted(data):
            if symbol not in CONTRACT_SIZE_USD:
                raise ValueError(f'Missing contract size for {symbol}')
            if (cutoff not in data[symbol]['spot'].index
                    or cutoff not in data[symbol]['futures'].index):
                continue
            spot = float(data[symbol]['spot'].at[cutoff, 'close'])
            futures = float(data[symbol]['futures'].at[cutoff, 'close'])
            premium_bps = (futures / spot - 1) * 10_000
            annualized_pct = premium_bps / 10_000 * 365 / config.days_before_expiry * 100
            coin_quantity = config.coin_purchase_usd / spot
            notional = _contract_notional(symbol, coin_quantity, futures)
            unhedged = (1 - notional / (coin_quantity * futures)
                        if notional > 0 else 1.0)
            if (premium_bps >= config.minimum_premium_bps
                    and annualized_pct >= config.minimum_annualized_premium_pct
                    and notional > 0
                    and unhedged <= config.maximum_unhedged_coin_fraction):
                candidates.append({
                    'symbol': symbol,
                    'premium_bps': premium_bps,
                    'annualized_premium_pct': annualized_pct,
                    'feature_contract_notional_usd': notional,
                    'feature_unhedged_coin_fraction': unhedged,
                })
        selected = max(
            candidates,
            key=lambda row: (
                row['premium_bps'],
                -sorted(data).index(row['symbol'])),
            default=None,
        )
        schedule.append({
            'expiry': expiry,
            'decision_time': decision,
            'feature_cutoff': cutoff,
            'entry_time': decision + pd.Timedelta(
                hours=config.execution_delay_hours),
            'planned_exit_time': expiry - pd.Timedelta(
                hours=config.exit_hours_before_expiry),
            'selected': selected,
            'all_candidates': candidates,
        })
    return schedule


def simulate_coin_carry(data, start, end, config, initial_capital=250.0):
    config.validate(initial_capital)
    start, end = _utc(start), _utc(end)
    for symbol, streams in data.items():
        _validate_hourly(
            streams['spot'], start, end, f'{symbol} spot', allow_gaps=True)
        _validate_hourly(streams['futures'], start, end, f'{symbol} COIN-M')
    schedule = build_coin_carry_schedule(data, start, end, config)
    spot_fee = config.costs.spot_fee_bps / 10_000
    futures_fee = config.costs.futures_fee_bps / 10_000
    spot_slip = config.costs.spot_slippage_bps / 10_000
    futures_slip = config.costs.futures_slippage_bps / 10_000
    realised = 0.0
    trades, equity_points = [], [initial_capital]
    global_min_collateral = config.coin_purchase_usd
    global_max_leverage = 0.0

    for item in schedule:
        selected = item['selected']
        if selected is None:
            continue
        symbol = selected['symbol']
        entry_time = item['entry_time']
        planned_exit = item['planned_exit_time']
        if any(timestamp not in data[symbol]['spot'].index
               or timestamp not in data[symbol]['futures'].index
               for timestamp in (entry_time, planned_exit)):
            continue
        spot_entry_reference = float(data[symbol]['spot'].at[entry_time, 'open'])
        futures_entry_reference = float(
            data[symbol]['futures'].at[entry_time, 'open'])
        spot_entry_fill = spot_entry_reference * (1 + spot_slip)
        futures_entry_fill = futures_entry_reference * (1 - futures_slip)
        coin_quantity = config.coin_purchase_usd / spot_entry_fill
        contract_notional = _contract_notional(
            symbol, coin_quantity, futures_entry_fill)
        if contract_notional <= 0:
            continue
        unhedged_fraction = 1 - contract_notional / (
            coin_quantity * futures_entry_fill)
        if unhedged_fraction > config.maximum_unhedged_coin_fraction:
            continue
        spot_entry_fee_usd = config.coin_purchase_usd * spot_fee
        futures_entry_fee_coin = (
            contract_notional * futures_fee / futures_entry_fill)
        exit_time, reason = planned_exit, 'PRE_EXPIRY_EXIT'
        episode_min_collateral = (
            coin_quantity - futures_entry_fee_coin) * futures_entry_fill
        episode_max_leverage = contract_notional / episode_min_collateral

        risk_path_end = planned_exit - pd.Timedelta(hours=1)
        for timestamp in pd.date_range(entry_time, risk_path_end, freq='1h'):
            futures_mark = float(data[symbol]['futures'].at[timestamp, 'close'])
            inverse_pnl_coin = contract_notional * (
                1 / futures_mark - 1 / futures_entry_fill)
            collateral_coin = (
                coin_quantity - futures_entry_fee_coin + inverse_pnl_coin)
            collateral_usd = collateral_coin * futures_mark
            leverage = (contract_notional / collateral_usd
                        if collateral_usd > 0 else float('inf'))
            episode_min_collateral = min(
                episode_min_collateral, collateral_usd)
            episode_max_leverage = max(episode_max_leverage, leverage)
            if timestamp in data[symbol]['spot'].index:
                spot_mark = float(data[symbol]['spot'].at[timestamp, 'close'])
                equity_points.append(
                    config.outside_reserve_usd - spot_entry_fee_usd
                    + collateral_coin * spot_mark + realised)
            if (collateral_usd < config.minimum_collateral_equity_usd
                    or leverage > config.maximum_futures_mark_leverage):
                requested = timestamp + pd.Timedelta(hours=1)
                common_exit = next((candidate for candidate in pd.date_range(
                    requested, planned_exit, freq='1h')
                    if candidate in data[symbol]['spot'].index
                    and candidate in data[symbol]['futures'].index), None)
                if common_exit is not None:
                    exit_time = common_exit
                    reason = ('RISK_COLLATERAL_EQUITY' if collateral_usd
                              < config.minimum_collateral_equity_usd
                              else 'RISK_FUTURES_LEVERAGE')
                    break

        spot_exit_reference = float(data[symbol]['spot'].at[exit_time, 'open'])
        futures_exit_reference = float(
            data[symbol]['futures'].at[exit_time, 'open'])
        spot_exit_fill = spot_exit_reference * (1 - spot_slip)
        futures_exit_fill = futures_exit_reference * (1 + futures_slip)
        inverse_pnl_coin = contract_notional * (
            1 / futures_exit_fill - 1 / futures_entry_fill)
        futures_exit_fee_coin = (
            contract_notional * futures_fee / futures_exit_fill)
        final_coin_before_fees = coin_quantity + inverse_pnl_coin
        final_coin = (final_coin_before_fees - futures_entry_fee_coin
                      - futures_exit_fee_coin)
        spot_exit_fee_usd = final_coin * spot_exit_fill * spot_fee
        ending_cash = (
            config.outside_reserve_usd - spot_entry_fee_usd
            + final_coin * spot_exit_fill - spot_exit_fee_usd)
        net = ending_cash - initial_capital

        reference_coin = config.coin_purchase_usd / spot_entry_reference
        reference_final_coin = reference_coin + contract_notional * (
            1 / futures_exit_reference - 1 / futures_entry_reference)
        reference_basis_pnl = (
            config.outside_reserve_usd
            + reference_final_coin * spot_exit_reference - initial_capital)
        price_only_cash = (
            config.outside_reserve_usd
            + final_coin_before_fees * spot_exit_fill)
        price_pnl_after_slippage = price_only_cash - initial_capital
        fees = (spot_entry_fee_usd + spot_exit_fee_usd
                + (futures_entry_fee_coin + futures_exit_fee_coin)
                * spot_exit_fill)
        slippage_cost = reference_basis_pnl - price_pnl_after_slippage
        realised += net
        global_min_collateral = min(
            global_min_collateral, episode_min_collateral)
        global_max_leverage = max(global_max_leverage, episode_max_leverage)
        trades.append({
            **item, **selected,
            'opened_at': entry_time,
            'closed_at': exit_time,
            'reason': reason,
            'spot_entry_reference': spot_entry_reference,
            'futures_entry_reference': futures_entry_reference,
            'spot_exit_reference': spot_exit_reference,
            'futures_exit_reference': futures_exit_reference,
            'coin_quantity': coin_quantity,
            'contract_notional_usd': contract_notional,
            'unhedged_coin_fraction': unhedged_fraction,
            'entry_basis_bps': (
                futures_entry_reference / spot_entry_reference - 1) * 10_000,
            'exit_basis_bps': (
                futures_exit_reference / spot_exit_reference - 1) * 10_000,
            'reference_basis_pnl': reference_basis_pnl,
            'price_pnl_after_slippage': price_pnl_after_slippage,
            'fees': fees,
            'slippage_cost': slippage_cost,
            'net_pnl': net,
            'min_collateral_equity_usd': episode_min_collateral,
            'max_futures_mark_leverage': episode_max_leverage,
        })
        equity_points.append(initial_capital + realised)

    pnls = np.asarray([row['net_pnl'] for row in trades], dtype=float)
    gains = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    losses = float(-pnls[pnls < 0].sum()) if len(pnls) else 0.0
    values = np.asarray(equity_points, dtype=float)
    drawdowns = (1 - values / np.maximum.accumulate(values)) * 100
    per_symbol = {
        symbol: {
            'episodes': sum(row['symbol'] == symbol for row in trades),
            'net_pnl': float(sum(
                row['net_pnl'] for row in trades if row['symbol'] == symbol)),
        }
        for symbol in data
    }
    return {
        'config': {
            **asdict(config),
            'headline_four_fill_rate_sum_bps':
                config.costs.headline_four_fill_rate_sum_bps,
        },
        'window': [str(start), str(end)],
        'schedule': schedule,
        'trades': trades,
        'summary': {
            'quarterly_decisions': len(schedule),
            'qualified_decisions': sum(
                item['selected'] is not None for item in schedule),
            'episodes': len(trades),
            'wins': int((pnls > 0).sum()) if len(pnls) else 0,
            'win_rate_pct': float((pnls > 0).mean() * 100) if len(pnls) else 0.0,
            'profit_factor': gains / losses if losses else (
                'Infinity' if gains else None),
            'reference_basis_pnl': float(sum(
                row['reference_basis_pnl'] for row in trades)),
            'fees': float(sum(row['fees'] for row in trades)),
            'slippage_cost': float(sum(
                row['slippage_cost'] for row in trades)),
            'net_pnl': float(pnls.sum()) if len(pnls) else 0.0,
            'return_pct': float(pnls.sum()) / initial_capital * 100 if len(pnls) else 0.0,
            'max_drawdown_pct': float(drawdowns.max()),
            'min_collateral_equity_usd': global_min_collateral,
            'max_futures_mark_leverage': global_max_leverage,
            'collateral_exhaustions': int(global_min_collateral <= 0),
            'per_symbol': per_symbol,
        },
    }
