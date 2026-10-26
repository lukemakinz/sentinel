# Paper protocol — Book A ALT+RM + Book B S83

## Kapitał

- Subkonto A: **$250** — `BOOK_A_ALT_RM` + `BOOK_A_RISK_DEFAULT`
- Subkonto B: **$250** — **S84 router** (`breadth ≥ 0.45` → v2, else v1)

## Cotygodniowo (poniedziałek UTC)

```bash
cd backend && PYTHONPATH=. ../env/bin/python -m backtest.run_book_ab_paper_snapshot
```

1. Zapisz `exposure_mult` i docelowe wagi A.
2. Rebalance A tylko jeśli mult > 0 i waga ≥ $15/pozycja.
3. B — nie rebalance; handel sygnałowy 1h Donchian gdy snapshot `regime OK: True`.

## Metryki tygodniowe

- $/dzień od startu paper
- Gap do $5 na **sumie** A+B
- `max_dd` vs backtest (−11% A, B zależnie od wariantu)

## Zamrożenie parametrów

Zmiana tylko po nowym `docs/research/*/protocol.json` + walk-forward.
