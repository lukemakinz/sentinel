from django.test import SimpleTestCase

from datetime import datetime, timezone

from l1_filter.ai_adjudicator import AICandidatePolicy, evaluate_ai_candidate, setup_fingerprint


class AICandidatePolicyTests(SimpleTestCase):
    def test_six_of_nine_with_structure_and_trigger_is_eligible(self):
        result = evaluate_ai_candidate(
            {'A1': False, 'A2': True, 'A3': False, 'A4': True, 'A5': True},
            {'B1': True, 'B2': True, 'B3': False, 'B5': False},
            {'C1': True, 'C2': False, 'C3': True, 'C4': True,
             'C5': False, 'C6': False, 'C7': False},
            AICandidatePolicy(min_passed=6, min_structural=2),
        )
        self.assertTrue(result['eligible'])
        self.assertEqual(result['passed_count'], 7)
        self.assertEqual(result['total_count'], 9)

    def test_high_count_cannot_override_unsafe_funding(self):
        result = evaluate_ai_candidate(
            {'A1': True, 'A2': True, 'A3': True, 'A4': False, 'A5': True},
            {'B1': True, 'B2': True, 'B3': True, 'B5': True},
            {'C1': True, 'C2': True, 'C3': True, 'C4': True,
             'C5': True, 'C6': True, 'C7': True},
        )
        self.assertFalse(result['eligible'])
        self.assertIn('unsafe_funding', result['hard_vetoes'])

    def test_correlated_execution_gates_count_as_one_criterion(self):
        result = evaluate_ai_candidate(
            {'A1': True, 'A2': True, 'A3': True, 'A4': True, 'A5': True},
            {'B1': True, 'B2': True, 'B3': True},
            {'C1': True, 'C3': True, 'C4': True, 'C5': True, 'C6': True, 'C7': True},
        )
        self.assertEqual(result['passed_count'], 9)
        self.assertEqual(result['criteria']['execution_confirmation'], True)

    def test_setup_fingerprint_is_stable_inside_same_structural_event(self):
        first = setup_fingerprint(
            'ETHUSDT', 'LONG', datetime(2026, 9, 10, 13, 1, tzinfo=timezone.utc),
            'ny', 100.0, (101.0, 102.0), 'CHoCH')
        second = setup_fingerprint(
            'ETHUSDT', 'LONG', datetime(2026, 9, 10, 13, 14, tzinfo=timezone.utc),
            'ny', 100.0, (101.0, 102.0), 'CHoCH')
        changed = setup_fingerprint(
            'ETHUSDT', 'LONG', datetime(2026, 9, 10, 13, 14, tzinfo=timezone.utc),
            'ny', 100.0, (101.0, 103.0), 'CHoCH')
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
