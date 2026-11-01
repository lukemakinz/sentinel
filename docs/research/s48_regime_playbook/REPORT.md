# S48 — regime playbook + early profit

Hash protokołu: `319e2360de95dc6b8e5725ca27f93258916bd5db72d65faabf6a289388bfda78`.

UP = tylko long continuation, DOWN = tylko short continuation, SIDELINE = brak transakcji (`trend_only`) albo fade failed breakout (`regime_switch`). Target 1.0R, time-stop 60 min, bez trailing.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S48_trend_only_early_profit | development | base | 285 | 48.1% | 0.6406217620224758 | $-15.13 | -6.052% | 6.052% |
| S48_trend_only_early_profit | development | stress | 142 | 35.9% | 0.3393252021324048 | $-14.84 | -5.934% | 6.040% |
| S48_trend_only_early_profit | development | severe | 117 | 28.2% | 0.2157075367356533 | $-15.02 | -6.006% | 6.018% |
| S48_trend_only_early_profit | validation | base | 283 | 47.0% | 0.6143722239026596 | $-14.77 | -5.910% | 6.053% |
| S48_trend_only_early_profit | validation | stress | 211 | 42.2% | 0.5373533438669521 | $-14.82 | -5.927% | 6.029% |
| S48_trend_only_early_profit | validation | severe | 138 | 31.2% | 0.35423769011245054 | $-14.83 | -5.932% | 6.001% |

- Decyzja dla `S48_trend_only_early_profit`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 2113, 'validation': 1209}.
- Udział reżimów 15m: {'UP': 0.299, 'DOWN': 0.284, 'SIDELINE': 0.417}.

| S48_regime_switch_early_profit | development | base | 202 | 45.0% | 0.5581785522421017 | $-14.93 | -5.973% | 6.014% |
| S48_regime_switch_early_profit | development | stress | 134 | 33.6% | 0.32503442366256746 | $-15.02 | -6.009% | 6.067% |
| S48_regime_switch_early_profit | development | severe | 124 | 27.4% | 0.21448164534893294 | $-15.15 | -6.059% | 6.059% |
| S48_regime_switch_early_profit | validation | base | 158 | 38.6% | 0.43528183918191693 | $-14.69 | -5.876% | 6.092% |
| S48_regime_switch_early_profit | validation | stress | 154 | 37.0% | 0.3884904605864776 | $-14.65 | -5.861% | 6.009% |
| S48_regime_switch_early_profit | validation | severe | 136 | 29.4% | 0.323822104846384 | $-14.38 | -5.751% | 6.019% |

- Decyzja dla `S48_regime_switch_early_profit`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 2777, 'validation': 1590}.
- Udział reżimów 15m: {'UP': 0.299, 'DOWN': 0.284, 'SIDELINE': 0.417}.

Kapitał $250, jeden wspólny rachunek SOL+XRP. Base 5/2 bps, stress 8/5, severe 10/10. Okno ograniczone do cache lokalnego.
