"""Run one watched-universe shadow cycle and resolve open plans."""
import json

from django.conf import settings
from django.core.management.base import BaseCommand

from ingester.models import WatchedPair
from l2_agents.auction_adjudicator import summarize_analysis_costs
from l2_agents.auction_service import analyze_symbol
from l2_agents.shadow_auction import resolve_open_plans


class Command(BaseCommand):
    help = 'Run one deduplicated auction-shadow cycle; never places orders.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--ai', action='store_true',
            help='Use the configured AI provider after deterministic preflight.',
        )
        parser.add_argument(
            '--symbol', action='append', dest='symbols',
            help='Analyze only this symbol; repeat the option for more symbols.',
        )
        parser.add_argument(
            '--no-resolve', action='store_true',
            help='Do not advance existing shadow plans after analysis.',
        )

    def handle(self, *args, **options):
        symbols = [s.upper() for s in (options['symbols'] or WatchedPair.get_active_symbols())]
        use_ai = bool(options['ai'])
        output = {
            'shadow_only': True,
            'execution_authorized': False,
            'ai_requested': use_ai,
            'configured_ai_default': bool(
                getattr(settings, 'AUCTION_SHADOW_AI_ENABLED', False)
            ),
            'analyses': [],
        }
        analysis_costs = []
        for symbol in symbols:
            result = analyze_symbol(
                symbol, use_ai=use_ai, persist=True, deduplicate_bar=True,
                baseline=True,
            )
            output['analyses'].append({
                'symbol': symbol,
                'analysis_id': result['analysis_id'],
                'created': result['created'],
                'action': result['decision']['action'],
                'direction': result['decision']['direction'],
                'strategy_id': result['decision']['strategy_id'],
                'data_quality': result['decision']['data_quality'],
                'runtime': result['runtime'],
                'baseline': result['baseline'],
                'analysis_cost': result['analysis_cost'],
            })
            analysis_costs.append(result['analysis_cost'])
        if not options['no_resolve']:
            output['resolver'] = resolve_open_plans()
        # Deliberately last in the human-facing response.
        output['analysis_cost'] = summarize_analysis_costs(analysis_costs)
        self.stdout.write(json.dumps(output, indent=2, default=str))
