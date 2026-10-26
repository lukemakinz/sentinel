from io import StringIO
import json

from django.core.management import call_command
from django.test import TestCase


class AuctionShadowReportTest(TestCase):
    def test_empty_report_refuses_promotion(self):
        output = StringIO()
        call_command('auction_shadow_report', stdout=output)
        report = json.loads(output.getvalue())

        self.assertEqual(report['plans']['CLOSED'], 0)
        self.assertFalse(report['evidence_gate']['sample_ready'])
        self.assertFalse(report['evidence_gate']['promotion_allowed'])
        self.assertEqual(list(report)[-1], 'analysis_cost')
        self.assertEqual(report['analysis_cost']['estimated_usd_known'], 0.0)
