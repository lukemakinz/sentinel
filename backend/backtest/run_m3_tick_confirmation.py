"""M3 -- event-conditioned tick screen. NOT a strategy. Question: does
order-flow's known-but-tiny predictive power (M1: ~0.1-0.14 bps median
decile spread) become large enough to matter when measured in the 3
seconds immediately after an LQX2 fresh_flow event, instead of
unconditionally on any random second of the day?

M2/M2b are closed (retrospective_evaluation holdout: filtering made
results WORSE, not better -- see run_m2b_oof_quality.py). This is a
different question: not "which events are good", but "does the market's
immediate tick-level reaction right after a forced-flow event carry
information M1's unconditional screen could not see".

Pipeline, exactly as frozen:
  1. Generate fresh_flow events with LQX2's EXACT, unmodified definition
     (l1_filter via run_lqx1_discovery.build_features/generate_events).
  2. Collect the unique (symbol, date) set actually touched by those
     events -- download ONLY those daily aggTrades archives, not 6
     months x 8 symbols unconditionally.
  3. NO LOOKAHEAD: the event exists only once its 15m bar has closed
     (event['timestamp'] IS that close time); tick confirmation uses
     STRICTLY LATER trades only (> event['timestamp']).
  4. Frozen 3-second confirmation window, three metrics, ONE frozen
     classification (no threshold sweep):
        flow_alignment    = event-direction aggressive volume /
                             total aggressive volume, in (t, t+3s]
        price_response_bps = signed (by event direction) price change
                             from event close to price at t+3s
        trade_velocity_ratio = trades/sec in (t, t+3s] over trades/sec
                             in the preceding 60s (before the event)
     Classification:
        CONTINUATION  : flow_alignment > 0.5 AND price_response_bps > 0
        ABSORPTION    : flow_alignment > 0.5 AND price_response_bps <= 0
        OPPOSITE_FLOW : flow_alignment <= 0.5
  5. Forward return (signed by event direction, bps) measured from the
     DECISION point (t+3s, not from the event itself) at +10s/+30s/+60s
     from there -- the honest, actionable framing: what a trader could
     capture starting from the moment they'd actually have the
     confirmation information.
  6. Report only -- median/mean signed bps, % symbol-days with correct
     sign, events/day in the CONTINUATION class, per-symbol breakdown,
     concentration. No sizing, no PF, no execution backtest at this
     stage.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from .download_agg_trades import load_agg_trades_day
from .metrics_data import load_metrics
from .run_lqx1_discovery import DEV_END as LQX_DEV_END, DEV_START as LQX_DEV_START
from .run_lqx1_discovery import WARMUP, build_features, generate_events
from .scalp_data import load_archives

TRADED = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT', 'SUIUSDT', 'DOGEUSDT')
CONFIRM_WINDOW_S = 3
VELOCITY_BASELINE_S = 60
HORIZONS_S = (10, 30, 60)
TICK_CACHE = '/tmp/sentinel-tick-cache'
RESULTS_PATH = '/tmp/sentinel-m3-results.csv'


def collect_fresh_flow_events():
    """LQX2's exact, unmodified event definition. Returns a dict
    symbol -> list of events (each a dict with timestamp/move_side/etc)."""
    cache = '/tmp/sentinel-scalp-cache'
    events_by_symbol = {}
    for symbol in TRADED:
        minutes, funding, _ = load_archives(symbol, WARMUP, LQX_DEV_END, cache)
        metrics, _ = load_metrics(symbol, WARMUP, LQX_DEV_END, cache)
        bars = build_features(minutes, metrics)
        dev_start_ts = pd.Timestamp(LQX_DEV_START, tz='UTC')
        dev_end_ts = pd.Timestamp(LQX_DEV_END, tz='UTC')
        events = [e for e in generate_events(bars, symbol)
                  if e['event_type'] == 'fresh_flow' and dev_start_ts <= e['timestamp'] < dev_end_ts]
        events_by_symbol[symbol] = events
        print(symbol, 'fresh_flow events:', len(events), flush=True)
    return events_by_symbol


def needed_symbol_dates(events_by_symbol):
    pairs = set()
    for symbol, events in events_by_symbol.items():
        for e in events:
            day = e['timestamp'].strftime('%Y-%m-%d')
            pairs.add((symbol, day))
    return sorted(pairs)


def stream_needed_days(pairs, events_by_symbol):
    """Downloads only the (symbol, date) aggTrades days actually needed,
    ONE AT A TIME: load the day, analyze that day's events, then delete
    the archive. Disk holds at most one daily file (~16MB for BTC) and RAM
    holds at most one day's trades, instead of ~5GB / all days at once.
    Per-day results are appended to RESULTS_PATH so a killed run resumes
    where it stopped. Resilient to individual failures (this environment
    has shown transient network timeouts against data.binance.vision) --
    skip and log, don't abort the whole run."""
    done = pd.read_csv(RESULTS_PATH, parse_dates=['timestamp']) if Path(RESULTS_PATH).exists() else pd.DataFrame()
    done_pairs = set(map(tuple, done[['symbol', 'date']].values)) if len(done) else set()
    events_by_pair = {}
    for symbol, events in events_by_symbol.items():
        for e in events:
            events_by_pair.setdefault((symbol, e['timestamp'].strftime('%Y-%m-%d')), []).append(e)

    failed = []
    for i, (symbol, day) in enumerate(pairs, 1):
        if (symbol, day) in done_pairs:
            continue
        try:
            trades = load_agg_trades_day(symbol, day, TICK_CACHE)
        except Exception as exc:
            failed.append((symbol, day, str(exc)[:120]))
            continue
        rows = [r for r in (analyze_event(e, symbol, {(symbol, day): trades}, set())
                            for e in events_by_pair[(symbol, day)]) if r is not None]
        # Marker row so a day with zero usable events is still recorded as done.
        rows = rows or [{'symbol': symbol, 'date': day, 'classification': 'NO_USABLE_EVENT'}]
        pd.DataFrame(rows).to_csv(RESULTS_PATH, mode='a', header=not Path(RESULTS_PATH).exists(), index=False)
        archive = Path(TICK_CACHE) / symbol / f'{symbol}-aggTrades-{day}.zip'
        archive.unlink(missing_ok=True)
        archive.with_suffix('.zip.CHECKSUM').unlink(missing_ok=True)
        del trades
        if i % 20 == 0:
            print(f'  processed {i}/{len(pairs)} symbol-days', flush=True)

    print(f'\nProcessed {len(pairs) - len(failed)}/{len(pairs)} needed symbol-days '
          f'({len(failed)} failed/skipped)')
    if failed:
        print('Failed (skipped, not retried further):', failed[:10],
              '...' if len(failed) > 10 else '')
    df = pd.read_csv(RESULTS_PATH, parse_dates=['timestamp'])
    return df[df.classification != 'NO_USABLE_EVENT']


def analyze_event(event, symbol, trades_cache, warned):
    ts = event['timestamp']
    day = ts.strftime('%Y-%m-%d')
    trades = trades_cache.get((symbol, day))
    if trades is None:
        return None

    move_side = event['move_side']
    event_close = event['close']

    baseline_start = ts - pd.Timedelta(seconds=VELOCITY_BASELINE_S)
    baseline = trades[(trades.index > baseline_start) & (trades.index <= ts)]
    if len(baseline) < 5:
        return None  # too quiet before the event to form a meaningful baseline
    baseline_rate = len(baseline) / VELOCITY_BASELINE_S

    confirm_end = ts + pd.Timedelta(seconds=CONFIRM_WINDOW_S)
    confirm = trades[(trades.index > ts) & (trades.index <= confirm_end)]  # NO LOOKAHEAD: strictly after ts
    if len(confirm) < 2:
        return None  # not enough post-event ticks to form flow_alignment

    aligned_vol = confirm.quantity[
        (confirm.is_buyer_maker == (move_side < 0))  # taker bought if not buyer-maker; aligned with move_side
    ].sum()
    total_vol = confirm.quantity.sum()
    if total_vol <= 0:
        return None
    flow_alignment = aligned_vol / total_vol

    price_at_confirm_end = confirm.price.iloc[-1]
    price_response_bps = move_side * (price_at_confirm_end / event_close - 1.0) * 10_000

    trade_velocity_ratio = (len(confirm) / CONFIRM_WINDOW_S) / baseline_rate if baseline_rate > 0 else np.nan

    if flow_alignment > 0.5 and price_response_bps > 0:
        classification = 'CONTINUATION'
    elif flow_alignment > 0.5 and price_response_bps <= 0:
        classification = 'ABSORPTION'
    else:
        classification = 'OPPOSITE_FLOW'

    forward = {}
    decision_ts = confirm_end
    decision_price = price_at_confirm_end
    for h in HORIZONS_S:
        target_ts = decision_ts + pd.Timedelta(seconds=h)
        window = trades[(trades.index > decision_ts) & (trades.index <= target_ts)]
        if window.empty:
            forward[h] = np.nan
            continue
        future_price = window.price.iloc[-1]
        forward[h] = move_side * (future_price / decision_price - 1.0) * 10_000

    return {
        'symbol': symbol, 'timestamp': ts, 'date': day, 'classification': classification,
        'flow_alignment': flow_alignment, 'price_response_bps': price_response_bps,
        'trade_velocity_ratio': trade_velocity_ratio,
        **{f'fwd_bps_{h}s': forward[h] for h in HORIZONS_S},
    }


def main():
    events_by_symbol = collect_fresh_flow_events()
    total_events = sum(len(v) for v in events_by_symbol.values())
    dev_days = (pd.Timestamp(LQX_DEV_END) - pd.Timestamp(LQX_DEV_START)).days
    print(f'\nTotal fresh_flow events: {total_events} ({total_events/dev_days:.2f}/day pooled, 8 symbols)')

    pairs = needed_symbol_dates(events_by_symbol)
    print(f'Unique (symbol, date) pairs needing aggTrades: {len(pairs)}')
    df = stream_needed_days(pairs, events_by_symbol)
    print(f'\nEvents with usable tick data: {len(df)} / {total_events} '
          f'(rest: missing day-data or too few ticks around the event)')

    print('\n' + '=' * 78)
    print('CLASSIFICATION BREAKDOWN')
    print('=' * 78)
    print(df.classification.value_counts())

    print('\n' + '=' * 78)
    print('FORWARD RETURN BY CLASSIFICATION (signed bps, from decision point t+3s)')
    print('=' * 78)
    for cls, g in df.groupby('classification'):
        events_per_day = len(g) / dev_days
        print(f'\n-- {cls} (n={len(g)}, {events_per_day:.2f}/day) --')
        for h in HORIZONS_S:
            col = f'fwd_bps_{h}s'
            valid = g[col].dropna()
            if len(valid) < 5:
                print(f'  +{h:>2d}s: insufficient data (n={len(valid)})')
                continue
            pct_correct_sign = (valid > 0).mean()
            print(f'  +{h:>2d}s: n={len(valid):>4d}  median={valid.median():>7.2f}bps  '
                  f'mean={valid.mean():>7.2f}bps  %correct_sign={pct_correct_sign*100:.1f}%')

    print('\n' + '=' * 78)
    print('CONTINUATION class: per-symbol breakdown (concentration check)')
    print('=' * 78)
    cont = df[df.classification == 'CONTINUATION']
    if len(cont):
        print(cont.groupby('symbol').agg(
            n=('fwd_bps_30s', 'size'),
            median_fwd_30s_bps=('fwd_bps_30s', 'median'),
            mean_fwd_30s_bps=('fwd_bps_30s', 'mean'),
        ))
    else:
        print('No CONTINUATION-classified events with usable data.')

    print('\nRound-trip cost reference (bps, from this project\'s own tiers): base=14, stress=26')


if __name__ == '__main__':
    main()
