# S49 — session opening-range breakout

Hash protokołu: `ae87220145f8d47b732019afbe7503f6c8648e0e0dd0a80628468b1df47c1caf`.

Zakres pierwszych 15 min UTC albo 30 min London, jedno wejście dziennie, tylko z 4h trendem (SIDELINE = skip). Target 1.0R, time-stop 90 min, bez trailing. To nie jest D1 (toczący się 1h high/low).

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S49_utc_open_with_trend | development | base | 91 | 36.3% | 0.35245795192607027 | $-12.38 | -4.953% | 5.103% |
| S49_utc_open_with_trend | development | stress | 69 | 30.4% | 0.2759153427732548 | $-11.94 | -4.775% | 4.870% |
| S49_utc_open_with_trend | development | severe | 45 | 20.0% | 0.1665382769248003 | $-11.09 | -4.437% | 4.447% |
| S49_utc_open_with_trend | validation | base | 56 | 35.7% | 0.2596218884195417 | $-10.23 | -4.093% | 4.243% |
| S49_utc_open_with_trend | validation | stress | 48 | 31.2% | 0.2510001103759992 | $-8.84 | -3.536% | 3.830% |
| S49_utc_open_with_trend | validation | severe | 36 | 19.4% | 0.1515822797214993 | $-7.98 | -3.190% | 3.356% |

- Decyzja dla `S49_utc_open_with_trend`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 114, 'validation': 66}.
- Udział reżimów 5m: {'UP': 0.299, 'DOWN': 0.284, 'SIDELINE': 0.417}.

| S49_london_with_trend | development | base | 90 | 41.1% | 0.6440596163678335 | $-6.06 | -2.423% | 3.136% |
| S49_london_with_trend | development | stress | 76 | 34.2% | 0.44952671236763836 | $-8.36 | -3.345% | 3.512% |
| S49_london_with_trend | development | severe | 55 | 36.4% | 0.333122266985386 | $-7.79 | -3.118% | 3.267% |
| S49_london_with_trend | validation | base | 61 | 39.3% | 0.4715439423817236 | $-7.26 | -2.903% | 3.628% |
| S49_london_with_trend | validation | stress | 52 | 36.5% | 0.3099631837278944 | $-8.72 | -3.488% | 3.884% |
| S49_london_with_trend | validation | severe | 29 | 31.0% | 0.289095404928605 | $-4.35 | -1.739% | 1.916% |

- Decyzja dla `S49_london_with_trend`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 111, 'validation': 71}.
- Udział reżimów 5m: {'UP': 0.299, 'DOWN': 0.284, 'SIDELINE': 0.417}.

Kapitał $250, jeden wspólny rachunek SOL+XRP. Base 5/2 bps, stress 8/5, severe 10/10. Okno ograniczone do cache lokalnego.
