"""Frozen chronological replay of XSM-28 beta-neutral pair momentum."""
import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from .cross_sectional_momentum import (
    XSMConfig,
    XSMCosts,
    simulate_xsm_pairs,
    weekly_xsm_targets,
)
from .swing_data import load_interval_archives


PROTOCOL_SHA256 = 'd7dbc97812ddbee754106ee60c8ed199bd49b715a5ae3138622a0b3029d494c3'
REFERENCE = 'BTCUSDT'
TRADED = ('ETHUSDT', 'SOLUSDT', 'BNBUSDT')
ALL_SYMBOLS = (REFERENCE, *TRADED)
WARMUP, END = '2021-01-01', '2026-09-01'
WINDOWS = {
    'development': ('2022-04-04', '2024-01-01'),
    'validation': ('2024-01-01', '2025-01-06'),
    'retrospective_evaluation': ('2025-01-06', END),
}


def _pf(summary):
    value = summary['episode_profit_factor']
    if value == 'Infinity':
        return float('inf')
    return float(value or 0)


def _development_pass(base, stress):
    return (base['episodes'] >= 4 and base['net_pnl'] > 0 and _pf(base) > 1.05
            and stress['net_pnl'] > 0)


def _validation_pass(base, stress):
    return (base['episodes'] >= 2 and base['net_pnl'] > 0 and _pf(base) > 1.10
            and stress['net_pnl'] >= 0 and _pf(stress) >= 1.00)


def _render_report(document):
    lines = [
        '# XSM-28 — cross-sectional beta-neutral momentum',
        '',
        f'Hash zamrożonego protokołu: `{document["protocol_sha256"]}`.',
        '',
        'ETH/SOL/BNB są co tydzień rangowane po 28-dniowym return/vol. '
        'Para powstaje tylko wtedy, gdy lider ma dodatni zwrot, a maruder ujemny; '
        'wagi neutralizują 60-dniową betę do BTC. Obie nogi są jednym epizodem '
        'w jednym ledgerze.',
        '',
        '| Okno | Koszty | Cele tygodniowe | Epizody | WR | PF | PnL | Zwrot | Max DD | Funding | Opłaty |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for window, row in document['windows'].items():
        for scenario, result in row['scenarios'].items():
            summary = result['summary']
            pf = summary['episode_profit_factor']
            pf = '—' if pf is None else pf
            lines.append(
                f'| {window} | {scenario} | {row["weekly_targets"]} | '
                f'{summary["episodes"]} | {summary["win_rate_pct"]:.1f}% | {pf} | '
                f'${summary["net_pnl"]:.2f} | {summary["return_pct"]:.3f}% | '
                f'{summary["max_drawdown_pct"]:.3f}% | ${summary["funding_pnl"]:.2f} | '
                f'${summary["fees"]:.2f} |')
    lines.extend([
        '',
        f'Decyzja: **{document["decision"]}**.',
        '',
        '## Interpretacja',
        '',
        '- Stop i target są liczone na łącznym, kosztowym PnL pary po zamknięciu '
        'baru 5m; obie nogi wychodzą dopiero na następnym open 5m.',
        '- Funding historyczny, opłata i poślizg są księgowane osobno dla obu nóg.',
        '- Wariant, który nie przejdzie development, nie otwiera kolejnych okien.',
        '- Przejście historycznych bramek oznaczałoby wyłącznie paper-forward; '
        'nie jest zgodą na handel live ani obietnicą zysku.',
        '- Mały, trzyaktywowowy przekrój i współdzielone czynniki ryzyka ograniczają '
        'siłę wniosku nawet przy dłuższym okresie kalendarzowym.',
        '',
    ])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='/tmp/sentinel-swing-cache')
    parser.add_argument('--output', default='docs/research/xsm_28')
    args = parser.parse_args()
    cache, output = Path(args.cache), Path(args.output)
    protocol_path = output / 'protocol.json'
    if not protocol_path.exists():
        raise FileNotFoundError('Frozen protocol.json must exist before loading data')
    actual_hash = sha256(protocol_path.read_bytes()).hexdigest()
    if actual_hash != PROTOCOL_SHA256:
        raise ValueError(
            f'Protocol changed after freeze: expected {PROTOCOL_SHA256}, got {actual_hash}')
    output.mkdir(parents=True, exist_ok=True)

    # allow_gaps=True: SOLUSDT's public daily archive is missing 5 calendar
    # days in early 2022 (2022-02-26..02-28 and 2022-04-01..04-02) — a real
    # gap in Binance's own historical archive, discovered here before any
    # signal or result was computed. The weekly ranking lookback (28
    # completed daily returns) simply has fewer observations across that
    # narrow window; 5m execution data is loaded separately per window
    # below and stays strictly continuous.
    daily, manifest = {}, {'daily': {}, 'execution': {}}
    for symbol in ALL_SYMBOLS:
        frame, _funding, entries = load_interval_archives(
            symbol, WARMUP, END, str(cache), interval='1d', allow_gaps=True)
        daily[symbol] = frame
        manifest['daily'][symbol] = entries
        print(symbol, 'verified daily archives ready', flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    base = XSMConfig()
    stress = replace(base, costs=XSMCosts(taker_fee_bps=8.0, slippage_bps=5.0))
    scenarios = {'base': base, 'stress': stress}
    document = {
        'protocol_sha256': actual_hash,
        'windows': {},
        'disclosure': (
            'Chronological historical research; 2025-2026 was seen in earlier strategy work '
            'and is not an untouched holdout.'),
    }

    def run_window(label):
        start, end = WINDOWS[label]
        targets = weekly_xsm_targets(
            {symbol: daily[symbol] for symbol in TRADED}, daily[REFERENCE],
            start, end, base, symbol_order=TRADED)
        markets = {}
        manifest['execution'][label] = {}
        for symbol in TRADED:
            frame, funding, entries = load_interval_archives(
                symbol, start, end, str(cache), interval='5m')
            markets[symbol] = frame, funding
            manifest['execution'][label][symbol] = entries
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        row = {'weekly_targets': len(targets), 'scenarios': {}}
        for scenario, config in scenarios.items():
            result = simulate_xsm_pairs(
                markets, targets, start, end, config, initial_capital=250.0)
            row['scenarios'][scenario] = result
            summary = result['summary']
            print(label, scenario, 'targets', len(targets), 'episodes', summary['episodes'],
                  'PF', summary['episode_profit_factor'],
                  f'PnL ${summary["net_pnl"]:.4f}', flush=True)
        document['windows'][label] = row
        return row

    development = run_window('development')
    if not _development_pass(
            development['scenarios']['base']['summary'],
            development['scenarios']['stress']['summary']):
        document['decision'] = 'REJECTED_AT_DEVELOPMENT_GATE'
    else:
        validation = run_window('validation')
        if not _validation_pass(
                validation['scenarios']['base']['summary'],
                validation['scenarios']['stress']['summary']):
            document['decision'] = 'REJECTED_AT_VALIDATION_GATE'
        else:
            run_window('retrospective_evaluation')
            document['decision'] = 'PAPER_FORWARD_ONLY_NOT_APPROVED_FOR_LIVE'

    (output / 'results.json').write_text(
        json.dumps(document, indent=2, default=str, allow_nan=False) + '\n')
    (output / 'REPORT.md').write_text(_render_report(document))


if __name__ == '__main__':
    main()
