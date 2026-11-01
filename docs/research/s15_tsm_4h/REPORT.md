# S15 — 4h time-series momentum / Donchian

Hash zamrożonego protokołu: `dcca133345ae4ab5753309dc4dcb615dc67df11b11bf794fe043de0346c393c6`.

To test retrospektywny, nie obietnica zysku ani zgoda na handel live. Każda polityka wyjścia przechodzi bramki samodzielnie.

| Prowadzenie pozycji | Okno | Koszty | Transakcje | WR | PF | PnL | Zwrot | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| initial_sl_only | development | base | 107 | 38.3% | 2.121975946776272 | $29.20 | 11.678% | 2.222% |
| initial_sl_only | development | stress | 107 | 38.3% | 2.020502805562486 | $26.71 | 10.684% | 2.190% |
| initial_sl_only | development | severe | 106 | 37.7% | 1.9502010304912902 | $24.56 | 9.822% | 2.159% |
| initial_sl_only | validation | base | 38 | 44.7% | 2.0174018666125275 | $7.72 | 3.088% | 2.218% |
| initial_sl_only | validation | stress | 38 | 44.7% | 1.8893145695312978 | $6.81 | 2.725% | 2.196% |
| initial_sl_only | validation | severe | 38 | 42.1% | 1.7532765031494553 | $5.84 | 2.335% | 2.173% |
| initial_sl_only | retrospective_evaluation | base | 77 | 23.4% | 0.8381811647787915 | $-4.06 | -1.625% | 3.932% |
| initial_sl_only | retrospective_evaluation | stress | 77 | 23.4% | 0.795377609254446 | $-5.15 | -2.062% | 4.053% |
| initial_sl_only | retrospective_evaluation | severe | 77 | 22.1% | 0.6874601543426628 | $-7.83 | -3.130% | 4.305% |

- Decyzja `initial_sl_only`: **REJECTED_BY_RETROSPECTIVE_DECAY**.

| delayed_cost_be | development | base | 109 | 35.8% | 2.13884796481222 | $28.83 | 11.531% | 2.034% |
| delayed_cost_be | development | stress | 109 | 35.8% | 2.0380033580064194 | $26.42 | 10.567% | 2.017% |
| delayed_cost_be | development | severe | 108 | 35.2% | 1.9698618504165166 | $24.34 | 9.738% | 2.020% |
| delayed_cost_be | validation | base | 41 | 34.1% | 1.6488654520175976 | $5.79 | 2.315% | 2.470% |
| delayed_cost_be | validation | stress | 41 | 34.1% | 1.550791785078565 | $4.95 | 1.978% | 2.430% |
| delayed_cost_be | validation | severe | 41 | 34.1% | 1.446838909284316 | $4.04 | 1.617% | 2.388% |
| delayed_cost_be | retrospective_evaluation | base | 78 | 24.4% | 0.8808419868365991 | $-2.85 | -1.141% | 3.538% |
| delayed_cost_be | retrospective_evaluation | stress | 78 | 24.4% | 0.837588764394904 | $-3.89 | -1.558% | 3.653% |
| delayed_cost_be | retrospective_evaluation | severe | 77 | 23.4% | 0.7857378596901263 | $-5.18 | -2.073% | 3.843% |

- Decyzja `delayed_cost_be`: **REJECTED_BY_RETROSPECTIVE_DECAY**.

| delayed_cost_be_chandelier | development | base | 129 | 37.2% | 1.701079005729949 | $21.51 | 8.604% | 2.207% |
| delayed_cost_be_chandelier | development | stress | 128 | 37.5% | 1.648202540757721 | $19.66 | 7.865% | 2.125% |
| delayed_cost_be_chandelier | development | severe | 127 | 37.0% | 1.5864588985563335 | $17.60 | 7.040% | 2.050% |
| delayed_cost_be_chandelier | validation | base | 48 | 43.8% | 1.6039785447942483 | $6.29 | 2.515% | 1.094% |
| delayed_cost_be_chandelier | validation | stress | 48 | 43.8% | 1.5129549344304563 | $5.37 | 2.148% | 1.107% |
| delayed_cost_be_chandelier | validation | severe | 48 | 43.8% | 1.4151941353754738 | $4.38 | 1.750% | 1.121% |
| delayed_cost_be_chandelier | retrospective_evaluation | base | 83 | 25.3% | 0.6571768490259455 | $-8.36 | -3.344% | 4.197% |
| delayed_cost_be_chandelier | retrospective_evaluation | stress | 83 | 25.3% | 0.6302054954275736 | $-8.94 | -3.577% | 4.254% |
| delayed_cost_be_chandelier | retrospective_evaluation | severe | 82 | 24.4% | 0.6018114913502396 | $-9.52 | -3.808% | 4.295% |

- Decyzja `delayed_cost_be_chandelier`: **REJECTED_BY_RETROSPECTIVE_DECAY**.

## Wykonanie i ryzyko

Kapitał $250; jeden wspólny portfel ETH/SOL/BNB; ryzyko do $0,50 na transakcję; notional do 50% equity; margin do 10% equity; dźwignia do 5x. Wszystkie wejścia i wyjścia są market, finansowanie historyczne jest rozliczone.

Cost-BE i Chandelier powstają wyłącznie po zamknięciu pełnej świecy 4h i działają od następnej świecy 5m. W niejednoznacznej świecy stary stop ma pierwszeństwo.
