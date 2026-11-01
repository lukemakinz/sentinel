# S53 — with-trend displacement continuation

Hash protokołu: `cfcdf3ad7f1b4e53162dd1917fc7bf2b876347b7ea5acf9a02eb2551372423fd`.

Impuls z trendy (duże body, close poza 12-bar extreme, volume), jedna próba na kubeł 4h. Target 1.0R, bez trailing. To nie jest pullback S48 ani fade zakresu S49-S52.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S53_displacement_5m | development | base | 223 | 48.4% | 0.5825984978786269 | $-14.74 | -5.897% | 6.011% |
| S53_displacement_5m | development | stress | 138 | 34.8% | 0.33012081302252805 | $-14.85 | -5.942% | 6.027% |
| S53_displacement_5m | development | severe | 77 | 31.2% | 0.302665589462149 | $-10.60 | -4.239% | 4.535% |
| S53_displacement_5m | validation | base | 199 | 46.7% | 0.4874470673233587 | $-14.94 | -5.977% | 6.064% |
| S53_displacement_5m | validation | stress | 156 | 41.0% | 0.4694028900408206 | $-14.30 | -5.721% | 5.874% |
| S53_displacement_5m | validation | severe | 72 | 37.5% | 0.436672607439973 | $-8.95 | -3.580% | 3.759% |

- Decyzja dla `S53_displacement_5m`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 633, 'validation': 375}.
- Udział reżimów: {'UP': 0.299, 'DOWN': 0.284, 'SIDELINE': 0.417}.

| S53_displacement_15m | development | base | 210 | 41.0% | 0.6078628429369566 | $-15.12 | -6.047% | 6.047% |
| S53_displacement_15m | development | stress | 156 | 37.8% | 0.44884580130726776 | $-15.11 | -6.043% | 6.049% |
| S53_displacement_15m | development | severe | 114 | 28.9% | 0.31387298851770495 | $-15.04 | -6.017% | 6.017% |
| S53_displacement_15m | validation | base | 140 | 46.4% | 0.7189751454048 | $-8.03 | -3.214% | 3.922% |
| S53_displacement_15m | validation | stress | 120 | 43.3% | 0.6164819929092332 | $-9.36 | -3.745% | 3.884% |
| S53_displacement_15m | validation | severe | 86 | 45.3% | 0.6475567402777401 | $-5.71 | -2.286% | 2.751% |

- Decyzja dla `S53_displacement_15m`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 281, 'validation': 158}.
- Udział reżimów: {'UP': 0.299, 'DOWN': 0.284, 'SIDELINE': 0.417}.

Kapitał $250, jeden wspólny rachunek SOL+XRP. Base 5/2 bps, stress 8/5, severe 10/10. Okno ograniczone do cache lokalnego.
