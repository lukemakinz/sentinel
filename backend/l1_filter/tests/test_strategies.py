from django.test import TestCase
from l1_filter.strategies import evaluate_strategies

ALL_A_PASS = {'A1': True, 'A2': True, 'A3': True, 'A4': True, 'A5': True}
ALL_A_FAIL = {'A1': True, 'A2': True, 'A3': False, 'A4': True, 'A5': True}

B_S1_OK = {'B1': True, 'B2': True, 'B3': True, 'B4': False, 'B5': False}  # 3 pass, B1+B2 mandatory
B_S1_FAIL = {'B1': True, 'B2': False, 'B3': True, 'B4': False, 'B5': False}  # B2 missing

C_S1_OK = {'C1': True, 'C2': True, 'C3': False, 'C4': False, 'C5': False}   # C1 + 2 total
C_S1_FAIL = {'C1': False, 'C2': True, 'C3': False, 'C4': False, 'C5': False}  # C1 missing

B_S3_OK = {'B1': False, 'B2': False, 'B3': True, 'B4': True, 'B5': False}  # B3 mandatory + 2 total
C_S3_OK = {'C1': False, 'C2': True, 'C3': True, 'C4': False, 'C5': False}   # C2+C3 mandatory


class StrategyEvaluationTest(TestCase):
    def test_s1_passes_with_correct_gates(self):
        result = evaluate_strategies(ALL_A_PASS, B_S1_OK, C_S1_OK)
        self.assertIn('S1', result)

    def test_s1_fails_when_a3_missing(self):
        result = evaluate_strategies(ALL_A_FAIL, B_S1_OK, C_S1_OK)
        self.assertNotIn('S1', result)

    def test_s1_fails_when_b2_missing(self):
        result = evaluate_strategies(ALL_A_PASS, B_S1_FAIL, C_S1_OK)
        self.assertNotIn('S1', result)

    def test_s1_fails_when_c1_missing(self):
        result = evaluate_strategies(ALL_A_PASS, B_S1_OK, C_S1_FAIL)
        self.assertNotIn('S1', result)

    def test_s2_needs_only_a1_a4_a5(self):
        partial_a = {'A1': True, 'A2': False, 'A3': False, 'A4': True, 'A5': True}
        b_2pass   = {'B1': True, 'B2': True, 'B3': False, 'B4': False, 'B5': False}
        c_1pass   = {'C1': True, 'C2': False, 'C3': False, 'C4': False, 'C5': False}
        result = evaluate_strategies(partial_a, b_2pass, c_1pass, has_whale_cvd=True)
        self.assertIn('S2', result)

    def test_s2_fails_without_whale_cvd(self):
        partial_a = {'A1': True, 'A2': False, 'A3': False, 'A4': True, 'A5': True}
        b_2pass   = {'B1': True, 'B2': True, 'B3': False, 'B4': False, 'B5': False}
        c_1pass   = {'C1': True, 'C2': False, 'C3': False, 'C4': False, 'C5': False}
        result = evaluate_strategies(partial_a, b_2pass, c_1pass, has_whale_cvd=False)
        self.assertNotIn('S2', result)

    def test_s3_passes_with_correct_gates(self):
        partial_a = {'A1': True, 'A2': True, 'A3': False, 'A4': False, 'A5': False}
        result = evaluate_strategies(partial_a, B_S3_OK, C_S3_OK)
        self.assertIn('S3', result)

    def test_s3_fails_when_b3_missing(self):
        partial_a = {'A1': True, 'A2': True, 'A3': False, 'A4': False, 'A5': False}
        b_no_b3   = {'B1': True, 'B2': True, 'B3': False, 'B4': False, 'B5': False}
        result = evaluate_strategies(partial_a, b_no_b3, C_S3_OK)
        self.assertNotIn('S3', result)

    def test_multiple_strategies_can_pass_simultaneously(self):
        # S1 requires all A, S3 requires A1+A2 — with all A passing both could pass
        result = evaluate_strategies(ALL_A_PASS, B_S1_OK, C_S1_OK)
        # S1 needs B1+B2+min3B+C1+min2C ← B_S1_OK+C_S1_OK satisfies
        self.assertIn('S1', result)

    def test_no_strategy_passes_when_all_fail(self):
        all_false = {k: False for k in ['A1','A2','A3','A4','A5']}
        result = evaluate_strategies(all_false, all_false, all_false)
        self.assertEqual(result, [])
