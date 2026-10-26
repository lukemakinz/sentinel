"""Deterministic X-of-Y admission policy for AI trade adjudication.

The quorum is deliberately built from independent *families* of evidence.
Several correlated C-gates therefore count as one execution-confirmation
criterion instead of inflating the score.  The policy only decides whether a
snapshot deserves AI review; it never authorizes execution.
"""
from dataclasses import dataclass
from hashlib import sha256
import json


AI_STRATEGY_ID = 'S12AI'
AI_POLICY_VERSION = 's12ai-quorum-v1'


@dataclass(frozen=True)
class AICandidatePolicy:
    min_passed: int = 7
    min_structural: int = 2
    min_execution_confirmations: int = 2


def setup_fingerprint(symbol: str, direction: str, observed_at, session: str | None,
                      swept_level=None, fvg_zone=None, structure_type=None) -> str:
    """Stable ID preventing the same structural event from calling AI each minute."""
    zone = tuple(round(float(value), 8) for value in (fvg_zone or ()))
    swept = round(float(swept_level), 8) if swept_level is not None else None
    payload = {
        'symbol': symbol,
        'direction': direction,
        'date': observed_at.date().isoformat(),
        'session': session,
        'swept_level': swept,
        'fvg_zone': zone,
        'structure_type': structure_type,
    }
    return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]


def evaluate_ai_candidate(gates_a: dict, gates_b: dict, gates_c: dict,
                          policy: AICandidatePolicy = AICandidatePolicy()) -> dict:
    """Return an auditable admission decision for the AI committee."""
    execution_count = sum(bool(gates_c.get(gate)) for gate in ('C3', 'C4', 'C5', 'C6', 'C7'))
    criteria = {
        'session_window': bool(gates_a.get('A1')),
        'htf_direction': bool(gates_a.get('A2')),
        'btc_alignment': bool(gates_a.get('A3')),
        'funding_safe': bool(gates_a.get('A4')),
        'trend_quality': bool(gates_a.get('A5')),
        'liquidity_or_location': bool(gates_b.get('B1') or gates_b.get('B3')),
        'delivery_zone': bool(gates_b.get('B2')),
        'structure_shift': bool(gates_c.get('C1')),
        'execution_confirmation': execution_count >= policy.min_execution_confirmations,
    }
    structural_keys = ('liquidity_or_location', 'delivery_zone', 'structure_shift')
    structural_count = sum(criteria[key] for key in structural_keys)
    passed_count = sum(criteria.values())

    hard_vetoes = []
    if not criteria['htf_direction']:
        hard_vetoes.append('no_htf_direction')
    if not criteria['funding_safe']:
        hard_vetoes.append('unsafe_funding')
    if structural_count < policy.min_structural:
        hard_vetoes.append('insufficient_structural_evidence')
    if not (criteria['structure_shift'] or gates_c.get('C7')):
        hard_vetoes.append('no_execution_trigger')

    return {
        'policy_version': AI_POLICY_VERSION,
        'eligible': passed_count >= policy.min_passed and not hard_vetoes,
        'passed_count': passed_count,
        'total_count': len(criteria),
        'required_count': policy.min_passed,
        'structural_count': structural_count,
        'required_structural_count': policy.min_structural,
        'execution_confirmation_count': execution_count,
        'criteria': criteria,
        'failed_criteria': [name for name, passed in criteria.items() if not passed],
        'hard_vetoes': hard_vetoes,
    }
