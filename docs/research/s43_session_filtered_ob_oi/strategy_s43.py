"""S43_session_wide -- najdalej zaszła strategia w całym projekcie (47
przetestowanych wariantów): jedyna, która przeszła zarówno bramkę
rozwojową, jak i walidacyjną. NIE zatwierdzona do prawdziwego kapitału --
w oknie retrospektywnym (kwiecień-wrzesień 2026, dane jeszcze
nieoglądane w momencie budowy strategii) przewaga się załamała
(PF spadł z 1.39/1.48 do 0.68). Pełne uczciwe wyniki w ZALOZENIA.md
w tym samym katalogu.

Ten plik jest samodzielny: bierze 1-minutowe świece OHLCV (open, high,
low, close, volume, taker_buy_volume) + 5-minutowe dane 'metrics' z
publicznego archiwum Binance (open_interest, toptrader_position_ratio)
i zwraca listę sygnałów wejścia (kierunek, cena referencyjna, stop).
Zarządzanie pozycją (partial/breakeven/trailing) opisane jest osobno
w EXECUTION_PARAMS poniżej -- silnik egzekucji (cluster_scalp_simulator)
to wspólna infrastruktura projektu, nie część tej konkretnej strategii,
więc nie jest tu duplikowany.

Mechanizm w skrócie:
  1. Order block (strefa popytu/podaży): świeca z displacementem
     >=1.5x ATR i wolumenem >=1.2x średniej, potwierdzona 3 świece
     później. Śledzona do pierwszego dotknięcia (retest) albo wygaśnięcia
     po 32 świecach 15-minutowych (~8h).
  2. Reżim: trend na 4h (EMA200 + nachylenie) potwierdzony ADX>=20 na 1h.
  3. Przepływ: OBV musi wspierać kierunek (powyżej/poniżej swojej EMA9).
  4. Open Interest: musi rosnąć przy longu / spadać przy shorcie w ciągu
     ostatnich 8 świec 15-minutowych -- nowe pozycje za ruchem, nie
     wyciskanie (squeeze) który się kończy.
  5. Filtr sesji (JEDYNA różnica względem bazowej strategii S20 H1):
     sygnał liczy się tylko jeśli godzina zamknięcia świecy (UTC) mieści
     się w [07:00, 20:00) -- okno Londyn+Nowy Jork, z pominięciem cichych
     godzin azjatyckich/nocnych.
"""
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import talib


# ---------------------------------------------------------------------------
# 1) Resampling 1-minutowych świec do 15m / 1h / 4h (closed-left, label-right)
# ---------------------------------------------------------------------------

def resample_closed(minutes: pd.DataFrame, interval: int) -> pd.DataFrame:
    rule = f'{interval}min'
    bars = minutes.resample(rule, label='right', closed='left').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last',
        'volume': 'sum', 'taker_buy_volume': 'sum'})
    counts = minutes.close.resample(rule, label='right', closed='left').count()
    return bars.loc[counts == interval].copy()  # odrzuca niepełne (dziurawe) świece


# ---------------------------------------------------------------------------
# 2) Konfiguracja -- wszystkie parametry strategii w jednym miejscu
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class S43Config:
    # -- order block / regime / flow (identyczne jak S17/S18/S20) --
    ema_period: int = 200
    ema_slope_lookback: int = 8
    adx_threshold: float = 20.0
    displacement_atr_mult: float = 1.5
    volume_mult: float = 1.2
    volume_avg_lookback: int = 20
    zone_ttl_bars: int = 32          # 32 x 15m = ~8h ważności strefy
    stop_buffer_atr_mult: float = 0.15
    obv_ema_period: int = 9
    # -- open interest --
    oi_lookback_bars: int = 8        # 8 x 15m = 2h
    # -- filtr sesji (jedyna nowość S43 względem S20 H1) --
    session_start_hour_utc: int = 7
    session_end_hour_utc: int = 20
    # -- zarządzanie pozycją (patient breakeven+chandelier z S20 H1) --
    partial_r: float = 1.5
    trail_atr: float = 2.5
    target_r: float = 8.0


# EXECUTION_PARAMS -- parametry silnika egzekucji (cluster_scalp_simulator /
# scalp_strategy.ScalpConfig), nie duplikowane tu jako kod, ale wypisane
# jawnie, bo są częścią definicji strategii:
EXECUTION_PARAMS = dict(
    timeframe_minutes=15,
    target_r=8.0,               # twardy cap: zamknij przy +8R
    partial_r=1.5,              # przy +1.5R: stop -> breakeven, aktywuj trailing
    trailing=True,
    trail_atr=2.5,              # chandelier trailing stop: 2.5x ATR od ekstremum
    max_hold_minutes=240,       # wymuszone zamknięcie po 4h, jeśli nic się nie wydarzyło
    fixed_risk_usd=0.50,        # stałe ryzyko $ na transakcję
    fixed_margin_usd=25.0,      # maks. depozyt zabezpieczający na pozycję
    risk_fraction=0.0020,       # 0.2% kapitału -- musi być spójne z fixed_risk_usd
    max_notional_equity=0.50,   # pozycja <= 50% kapitału w wartości nominalnej
    max_margin_fraction=0.10,   # <= 10% kapitału w depozycie
    leverage=5.0,
    daily_loss_fraction=0.006,  # dzienny stop strat
    min_reward_cost_ratio=3.0,  # odrzuć sygnał, jeśli oczekiwany zysk < 3x szacowany koszt
    fee_bps_base=5.0, slippage_bps_base=2.0, maker_fee_bps_base=2.0,
    limit_penetration_bps_base=2.0,
    ambiguous_bar_rule='stop first; brak korzystnego wyjścia w minucie fill limitu',
)


# ---------------------------------------------------------------------------
# 3) Cechy: order block, reżim 4h, OBV, ATR, OI
# ---------------------------------------------------------------------------

def order_block_features(minutes: pd.DataFrame, config: S43Config) -> pd.DataFrame:
    bars = resample_closed(minutes, 15)
    close = bars.close.to_numpy()
    bars['atr'] = talib.ATR(bars.high.to_numpy(), bars.low.to_numpy(), close, timeperiod=14)
    bars['obv'] = (np.sign(bars.close.diff().fillna(0.0)) * bars.volume).cumsum()
    bars['obv_ema'] = bars.obv.ewm(span=config.obv_ema_period, adjust=False).mean()

    hourly = resample_closed(minutes, 60)
    hourly['adx'] = talib.ADX(hourly.high.to_numpy(), hourly.low.to_numpy(),
                              hourly.close.to_numpy(), timeperiod=14)
    bars['htf_adx'] = hourly.adx.reindex(bars.index, method='ffill')

    four_hour = resample_closed(minutes, 240)
    four_hour['ema'] = talib.EMA(four_hour.close.to_numpy(), timeperiod=config.ema_period)
    slope = four_hour.ema - four_hour.ema.shift(config.ema_slope_lookback)
    four_hour['trend_up'] = (four_hour.close > four_hour.ema) & (slope > 0)
    four_hour['trend_down'] = (four_hour.close < four_hour.ema) & (slope < 0)
    bars['htf_trend_up'] = four_hour.trend_up.reindex(
        bars.index, method='ffill').infer_objects(copy=False).fillna(False).astype(bool)
    bars['htf_trend_down'] = four_hour.trend_down.reindex(
        bars.index, method='ffill').infer_objects(copy=False).fillna(False).astype(bool)

    # Order block potwierdzony 3 świece po uformowaniu (idx = j - 3), liczony
    # wyłącznie z danych dostępnych w świecy potwierdzającej j (bez zaglądania w przyszłość).
    open_idx = bars.open.shift(3)
    close_idx = bars.close.shift(3)
    atr_idx = bars.atr.shift(3)
    displacement = bars.close - close_idx
    volume_peak = bars.volume.rolling(3).max()
    volume_baseline = bars.volume.shift(4).rolling(config.volume_avg_lookback).mean()
    volume_ok = volume_peak >= config.volume_mult * volume_baseline

    prior_candle_bearish = close_idx < open_idx  # -> strefa popytu (bull OB)
    prior_candle_bullish = close_idx > open_idx  # -> strefa podaży (bear OB)

    bars['ob_bull_confirmed'] = (
        prior_candle_bearish & volume_ok
        & (displacement >= config.displacement_atr_mult * atr_idx)
    ).fillna(False)
    bars['ob_bull_top'] = open_idx
    bars['ob_bull_bottom'] = close_idx

    bars['ob_bear_confirmed'] = (
        prior_candle_bullish & volume_ok
        & (-displacement >= config.displacement_atr_mult * atr_idx)
    ).fillna(False)
    bars['ob_bear_top'] = close_idx
    bars['ob_bear_bottom'] = open_idx
    return bars


def oi_features(minutes: pd.DataFrame, metrics: pd.DataFrame, config: S43Config) -> pd.DataFrame:
    """`metrics`: 5-minutowe archiwum Binance (open_interest, ...),
    ładowane przez backend/backtest/metrics_data.py::load_metrics."""
    bars = order_block_features(minutes, config)
    aligned = metrics.reindex(bars.index, method='ffill')
    bars = bars.join(aligned)
    bars['oi_change'] = bars.open_interest - bars.open_interest.shift(config.oi_lookback_bars)
    return bars


# ---------------------------------------------------------------------------
# 4) Generowanie sygnałów: order block retest + reżim + flow + OI + sesja
# ---------------------------------------------------------------------------

def generate_signals(bars: pd.DataFrame, config: S43Config, symbol: str) -> list[dict]:
    n = len(bars)
    atr = bars.atr.to_numpy()
    low, high, close = bars.low.to_numpy(), bars.high.to_numpy(), bars.close.to_numpy()
    htf_trend_up, htf_trend_down = bars.htf_trend_up.to_numpy(), bars.htf_trend_down.to_numpy()
    htf_adx = bars.htf_adx.to_numpy()
    obv, obv_ema = bars.obv.to_numpy(), bars.obv_ema.to_numpy()
    oi_change = bars.oi_change.to_numpy()
    ob_bull_confirmed = bars.ob_bull_confirmed.to_numpy()
    ob_bull_top, ob_bull_bottom = bars.ob_bull_top.to_numpy(), bars.ob_bull_bottom.to_numpy()
    ob_bear_confirmed = bars.ob_bear_confirmed.to_numpy()
    ob_bear_top, ob_bear_bottom = bars.ob_bear_top.to_numpy(), bars.ob_bear_bottom.to_numpy()

    active = {1: [], -1: []}
    records = []
    for i in range(n):
        # wygaśnięcie stref starszych niż zone_ttl_bars
        active[1] = [z for z in active[1] if z['expires'] > i]
        active[-1] = [z for z in active[-1] if z['expires'] > i]

        if ob_bull_confirmed[i] and np.isfinite(ob_bull_top[i]) and np.isfinite(ob_bull_bottom[i]):
            active[1].append({'top': float(ob_bull_top[i]), 'bottom': float(ob_bull_bottom[i]),
                              'expires': i + config.zone_ttl_bars})
        if ob_bear_confirmed[i] and np.isfinite(ob_bear_top[i]) and np.isfinite(ob_bear_bottom[i]):
            active[-1].append({'top': float(ob_bear_top[i]), 'bottom': float(ob_bear_bottom[i]),
                               'expires': i + config.zone_ttl_bars})

        if not np.isfinite(atr[i]):
            continue

        for side in (1, -1):
            if side == 1:
                touched = [z for z in active[1] if low[i] <= z['top'] and close[i] >= z['bottom']]
            else:
                touched = [z for z in active[-1] if high[i] >= z['bottom'] and close[i] <= z['top']]
            if not touched:
                continue
            for z in touched:
                active[side].remove(z)  # "pierwsze dotknięcie" -- jedna próba na strefę

            # (1) reżim
            regime_ok = htf_trend_up[i] if side == 1 else htf_trend_down[i]
            if not (regime_ok and htf_adx[i] >= config.adx_threshold):
                continue
            # (2) przepływ (OBV)
            flow_ok = obv[i] > obv_ema[i] if side == 1 else obv[i] < obv_ema[i]
            if not flow_ok:
                continue
            # (3) open interest
            if not np.isfinite(oi_change[i]):
                continue
            oi_ok = oi_change[i] >= 0 if side == 1 else oi_change[i] <= 0
            if not oi_ok:
                continue
            # (4) filtr sesji -- JEDYNA różnica względem S20 H1
            hour = bars.index[i].hour
            if not (config.session_start_hour_utc <= hour < config.session_end_hour_utc):
                continue

            zone = touched[0]
            stop = (zone['bottom'] - config.stop_buffer_atr_mult * atr[i] if side == 1
                    else zone['top'] + config.stop_buffer_atr_mult * atr[i])
            risk = side * (close[i] - stop)
            if risk <= 0:
                continue
            direction = 'long' if side == 1 else 'short'
            records.append({
                'timestamp': bars.index[i], 'side': side, 'reference': float(close[i]),
                'stop': float(stop), 'min_stop_atr': 0.5, 'max_stop_atr': 3.0,
                'atr': float(atr[i]), 'score': 6,
                'setup': f'order_block_oi_session_{symbol}',
                'setup_id': f'S43:v1:{symbol}:{direction}:{bars.index[i].isoformat()}',
            })

    records.sort(key=lambda item: item['timestamp'])
    counts = Counter(item['timestamp'] for item in records)
    return [item for item in records if counts[item['timestamp']] == 1]  # zbieg = odrzuć oba
