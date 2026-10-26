# Zamrożony stack Book A + B (research → paper)

| Księga | ID | Kapitał | Uwagi |
|--------|-----|--------:|-------|
| A | `BOOK_A_ALT_RM` + `RM_composite_v1` | $250 | Alty TSMOM, BTC tylko SMA200 gate |
| B | `S84_quiet_router` (S86: + low vol) | $250 | breadth≥0.45 **lub** (vol&lt;35% i breadth≥25%) → v2 |

## Komendy

```bash
cd backend
PYTHONPATH=. ../env/bin/python -m backtest.run_portfolio_two_books_research
PYTHONPATH=. ../env/bin/python -m backtest.run_s85_portfolio_combo_research
PYTHONPATH=. ../env/bin/python -m backtest.run_book_ab_paper_snapshot
```

## Cel $5/d

Śledź **combined $/dzień** i gap.

| Combo (S85) | validation | full 2025 |
|-------------|----------:|----------:|
| **Router (S84/86)** | **+$0,41/d** | +$0,49/d |
| **B v2 only** | +$0,31/d | **+$0,60/d** |

Paper: **router** (lepszy validation). W bull: rozważ ręcznie **v2**.

## Fuse (eksperymentalny)

`trailing_pause_fuse` w S85 — tylko research (górne oszacowanie); nie wdrażać live bez forwardu.
