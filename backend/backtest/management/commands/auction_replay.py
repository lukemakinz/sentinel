"""Historical replay of frozen M0 / M1 / M3 on Binance public archives.

    python manage.py auction_replay --start 2024-01-01 --end 2026-10-01

Resumable: per-symbol records are written as soon as a symbol finishes and
are reused on the next run.  Writes records, breadth universes, summary and a
REPORT.md into --out.  Never touches the trading database.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand

from backtest.auction_replay import (
    REPLAY_ASSUMPTIONS, REPLAY_VERSION, Replay, build_breadth_by_quarter, run_plugin,
)
from backtest.auction_replay_stats import summarize, verdict

DEFAULT_OUT = Path(settings.BASE_DIR).parent / 'docs' / 'research' / 'auction_replay_v1_2'
CORE_TARGETS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']


class Command(BaseCommand):
    help = 'Replay frozen M0/M1/M3 over historical archives (research only).'

    def add_arguments(self, parser):
        parser.add_argument('--start', default='2024-01-01')
        parser.add_argument('--end', default='2026-10-01')
        parser.add_argument('--targets', default='',
                            help='Comma list; default BTC, ETH, SOL + 7 PIT alts at --start.')
        parser.add_argument('--extra-alts', type=int, default=7)
        parser.add_argument('--cache', default=settings.PAPER_FORWARD_CACHE)
        parser.add_argument('--out', default=str(DEFAULT_OUT))
        parser.add_argument('--usd-per-r', type=float, default=1.25,
                            help='$ per 1R: 0.5%% risk on $250 = $1.25.')
        parser.add_argument('--strategy', default='',
                            help='Replay this registered plugin (generic path) instead of frozen M0.')
        parser.add_argument('--slippage-bps', type=float, default=None,
                            help='Override PAPER_MARKET_SLIPPAGE_BPS for this run (stress scenario).')
        parser.add_argument('--breadth-file', default='',
                            help='Reuse an existing point-in-time breadth_by_quarter.json.')

    def handle(self, *args, **opt):
        start, end = pd.Timestamp(opt['start'], tz='UTC'), pd.Timestamp(opt['end'], tz='UTC')
        out = Path(opt['out'])
        out.mkdir(parents=True, exist_ok=True)

        if opt['slippage_bps'] is not None:
            settings.PAPER_MARKET_SLIPPAGE_BPS = opt['slippage_bps']
        breadth_path = out / 'breadth_by_quarter.json'
        if not breadth_path.exists() and opt['breadth_file']:
            breadth_path.write_text(Path(opt['breadth_file']).read_text())
        if breadth_path.exists():
            breadth = json.loads(breadth_path.read_text())
        else:
            self.stdout.write('Selecting point-in-time breadth universes...')
            breadth = build_breadth_by_quarter(start, end, opt['cache'])
            breadth_path.write_text(json.dumps(breadth, indent=2))
        first_quarter = sorted(breadth)[0]

        if opt['targets']:
            targets = [s.strip().upper() for s in opt['targets'].split(',') if s.strip()]
        else:
            extra = [s for s in breadth[first_quarter] if s not in CORE_TARGETS]
            targets = CORE_TARGETS + extra[:opt['extra_alts']]
        self.stdout.write(f'Targets: {targets}')

        replay = Replay(start=start, end=end, cache=opt['cache'], breadth_by_quarter=breadth)
        records = []
        for target in targets:
            path = out / f'records_{target}.json'
            if path.exists():
                records += json.loads(path.read_text())
                self.stdout.write(f'{target}: reused {path.name}')
                continue
            started = time.monotonic()
            progress = lambda s, t, n: self.stdout.write(f'  {s} {t:%Y-%m-%d} candidates={n}')  # noqa: E731
            rows = (run_plugin(replay, target, opt['strategy'], progress=progress) if opt['strategy']
                    else replay.run_symbol(target, progress=progress))
            path.write_text(json.dumps(rows, default=str))
            records += rows
            replay.drop(target)
            self.stdout.write(f'{target}: {len(rows)} candidates in {time.monotonic() - started:.0f}s')

        summary = summarize(records, start=start, end=end, usd_per_r=opt['usd_per_r'])
        summary.update({
            'version': REPLAY_VERSION, 'start': str(start.date()), 'end': str(end.date()),
            'targets': targets, 'assumptions': REPLAY_ASSUMPTIONS,
            'strategy': opt['strategy'] or 'M0_FROZEN',
            'slippage_bps': float(getattr(settings, 'PAPER_MARKET_SLIPPAGE_BPS', 5)),
            'verdict': verdict(summary) if summary.get('candidates') else [],
        })
        (out / 'summary.json').write_text(json.dumps(summary, indent=2, default=str))
        (out / 'REPORT.md').write_text(render_report(summary, breadth))
        self.stdout.write(self.style.SUCCESS(f'Wrote {out / "REPORT.md"}'))
        for line in summary.get('verdict', []):
            self.stdout.write(line)


def render_report(s: dict, breadth: dict) -> str:
    if not s.get('candidates'):
        return '# Auction replay\n\nNo candidates.\n'
    p = s['policies']
    lines = [
        f"# Historical replay {s['version']}: M0 / M1 / M3",
        '',
        f"Period {s['start']} → {s['end']} ({s['days']} days), targets: {', '.join(s['targets'])}.",
        f"Candidates: {s['candidates']}. Rules are frozen for this retrospective run; "
        'this history is diagnostic, not a claim of out-of-sample performance.',
        '',
        '## Verdict',
        *[f'- {line}' for line in s['verdict']],
        '',
        '## Policies (live shadow cost model)',
        '',
        '| | kept | filled | WR | E/trade R | E/candidate R | total R | PF | max DD R | $/day | cost R |',
        '|---|---|---|---|---|---|---|---|---|---|---|',
    ]
    for key, label in (('m0', 'M0 baseline'), ('m1', 'M1 + trend'), ('m3', 'M3 + global')):
        x = p[key]
        lines.append(
            f"| {label} | {x['candidates_kept']} | {x['filled_trades']} | {x['win_rate']} | "
            f"{x['expectancy_per_trade_r']} | {x['expectancy_per_candidate_r']} | {x['total_r']} | "
            f"{x['profit_factor']} | {x['max_drawdown_r']} | {x['usd_per_day']} | {x['avg_cost_r']} |")
    u = s['paired_uplift_vs_m0']
    ci = s['expectancy_per_candidate_ci']
    lines += [
        '',
        f"$/day assumes ${s['usd_per_r']} per 1R (0.5% risk on $250). Target: $5/day.",
        '',
        '## Paired uplift vs M0 (per candidate, day-block bootstrap 95% CI)',
        '',
        f"- M1 − M0: {u['m1']['mean']} R, CI {u['m1']['ci95']}, P(≤0) {u['m1']['p_le_0']}",
        f"- M3 − M0: {u['m3']['mean']} R, CI {u['m3']['ci95']}, P(≤0) {u['m3']['p_le_0']}",
        f"- M0 expectancy per candidate: {ci['m0']['mean']} R, CI {ci['m0']['ci95']}",
        f"- Mean M0 outcome of candidates vetoed: M1 {s['vetoed_candidate_mean_r']['m1']} R, "
        f"M3 {s['vetoed_candidate_mean_r']['m3']} R (negative = veto removed losers).",
        '',
        '## Intraday management on the same fills',
        '',
        '| policy | filled | TP1 hit | WR | E/trade R | E/candidate R | total R | PF | max DD R | $/day |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
        *[
            f"| {policy.upper()} | {value['filled_trades']} | {value['tp1_hit_rate']} | "
            f"{value['win_rate']} | {value['expectancy_per_trade_r']} | "
            f"{value['expectancy_per_candidate_r']} | {value['total_r']} | "
            f"{value['profit_factor']} | {value['max_drawdown_r']} | {value['usd_per_day']} |"
            for policy, value in s['management_policies'].items()
        ],
        '',
        *[
            f"- {policy.upper()} − P0: {value['mean']} R/candidate, CI {value['ci95']}, "
            f"P(≤0) {value['p_le_0']}"
            for policy, value in s['management_uplift_vs_p0'].items()
        ],
        '',
        s['multiple_testing_note'],
        '',
        '## Stability by year (total R)',
        '',
        '| year | candidates | M0 | M1 | M3 |',
        '|---|---|---|---|---|',
        *[f"| {y} | {v['candidates']} | {v['m0']} | {v['m1']} | {v['m3']} |"
          for y, v in sorted(s['by_year'].items())],
        '',
        '## By symbol (total R)',
        '',
        '| symbol | candidates | filled | M0 | M1 | M3 |',
        '|---|---|---|---|---|---|',
        *[f"| {k} | {v['candidates']} | {v['filled']} | {v['m0']} | {v['m1']} | {v['m3']} |"
          for k, v in sorted(s['by_symbol'].items())],
        '',
        '## M0 by global-context state at the candidate',
        '',
        '| state | candidates | filled | M0 mean R / candidate |',
        '|---|---|---|---|',
        *[f"| {k} | {v['candidates']} | {v['filled']} | {v['m0_mean_r_per_candidate']} |"
          for k, v in sorted(s['by_global_state_m0'].items())],
        '',
        f"Exit reasons: {s['exit_reasons']}",
        '',
        '## Assumptions and deviations from live',
        '',
        *[f'- **{k}**: {v}' for k, v in s['assumptions'].items()],
        '',
        '## Point-in-time breadth universes',
        '',
        *[f'- {q}: {", ".join(v)}' for q, v in sorted(breadth.items())],
        '',
    ]
    return '\n'.join(lines)
