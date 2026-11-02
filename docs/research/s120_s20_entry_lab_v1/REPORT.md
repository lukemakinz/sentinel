# S120 — S20 Entry & Management Lab, Stage A

Protocol hash: `25cb6949b70725aab7e5a30284951df1b74a17d8a444fcf0899901e1b8533784`.

**Retrospective walk-forward diagnostic only. Live remains disabled.**

Only entry timing changes. Candidate formation, structural stop, sizing, risk brakes and the S20 patient runner are frozen.

## fold_1

| Policy | Train stress fills | Train PF | Train mean R | Train PnL | Test stress fills | Test PF | Test mean R | Test PnL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MARKET_TOUCH | 139 | 0.764188711752935 | -0.121 | $-7.74 | 42 | 0.8567638736588714 | -0.062 | $-1.32 |
| SWEEP_RECLAIM | 9 | 0.5908109331671713 | -0.226 | $-1.02 | 1 | Infinity | 4.222 | $2.11 |
| MSS_BREAK | 59 | 0.5816941579217293 | -0.227 | $-6.62 | 18 | 1.5495786723777054 | 0.173 | $1.55 |
| MSS_RETEST | 42 | 0.5048453938681624 | -0.335 | $-6.85 | 15 | 0.37077981817460554 | -0.188 | $-1.41 |

Selected from train only: **CASH**.

## fold_2

| Policy | Train stress fills | Train PF | Train mean R | Train PnL | Test stress fills | Test PF | Test mean R | Test PnL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MARKET_TOUCH | 181 | 0.7754612992236823 | -0.107 | $-8.38 | 85 | 0.22810722728789073 | -0.492 | $-15.21 |
| SWEEP_RECLAIM | 10 | 1.4331771043779857 | 0.218 | $1.08 | 7 | 0.2504913746750656 | -0.492 | $-1.72 |
| MSS_BREAK | 77 | 0.724708330073031 | -0.133 | $-5.12 | 40 | 0.2980434918383337 | -0.375 | $-7.41 |
| MSS_RETEST | 57 | 0.4865950362320936 | -0.296 | $-8.22 | 30 | 0.49094716254968934 | -0.271 | $-4.04 |

Selected from train only: **CASH**.

## Combined disjoint OOS tests

| Policy | Fills | PF | Mean R | PnL | Fold PnL | Bootstrap lower | Gate |
|---|---:|---:|---:|---:|---|---:|---|
| MARKET_TOUCH | 127 | 0.42883583118352714 | -0.350 | $-16.53 | [-1.3239758083800552, -15.210585791670098] | -0.511 | FAIL |
| SWEEP_RECLAIM | 8 | 1.17179691062597 | 0.098 | $0.39 | [2.111096535163142, -1.7174379185350688] | -0.884 | FAIL |
| MSS_BREAK | 58 | 0.5619217077225243 | -0.205 | $-5.86 | [1.5497343880938104, -7.408669063843689] | -0.442 | FAIL |
| MSS_RETEST | 45 | 0.4644828394406304 | -0.243 | $-5.45 | [-1.4097373725350053, -4.0382317178025176] | -0.474 | FAIL |

## Walk-forward selection path

Fold selections: `['CASH', 'CASH']`.

Fills 0, PF None, mean R 0.000, PnL $0.00.

**Decision: REJECTED_NO_ENTRY_POLICY_PASSES_OOS_GATE.**

A failed Stage A means stop/TP tuning is not allowed to rescue the entry stream. A passing fixed policy would authorize a new, separately frozen Stage B management study only.
