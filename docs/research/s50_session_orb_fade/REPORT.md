# S50 — fade failed session opening-range break

Hash protokołu: `c0f64a25bca11d6f7e89cdf586b84f18f78cd20b50d268251c671d628d9b9494`.

Po S49 (z-trendem ORB odrzucony) testujemy hipotezę komplementarną: pierwsze wybicie zakresu sesji jest fałszywe; fade po reclaim. Jedno wejście dziennie. Target 1.0R, time-stop 90 min, bez trailing.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S50_utc_failed_fade | development | base | 150 | 52.7% | 0.6695738739053134 | $-10.34 | -4.136% | 4.136% |
| S50_utc_failed_fade | development | stress | 82 | 50.0% | 0.6029575369625432 | $-6.29 | -2.514% | 2.741% |
| S50_utc_failed_fade | development | severe | 56 | 53.6% | 0.6690045589423463 | $-3.05 | -1.220% | 1.392% |
| S50_utc_failed_fade | validation | base | 84 | 45.2% | 0.5819684860358068 | $-7.70 | -3.080% | 3.182% |
| S50_utc_failed_fade | validation | stress | 51 | 49.0% | 0.5506813888343713 | $-4.48 | -1.793% | 2.063% |
| S50_utc_failed_fade | validation | severe | 28 | 42.9% | 0.38673892771116847 | $-3.36 | -1.344% | 1.639% |

- Decyzja dla `S50_utc_failed_fade`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 245, 'validation': 147}.
- Udział reżimów 5m: {'UP': 0.299, 'DOWN': 0.284, 'SIDELINE': 0.417}.

| S50_london_sideline_fade | development | base | 66 | 39.4% | 0.29259088367224356 | $-10.77 | -4.310% | 4.448% |
| S50_london_sideline_fade | development | stress | 32 | 40.6% | 0.43145182931296555 | $-3.62 | -1.448% | 1.646% |
| S50_london_sideline_fade | development | severe | 19 | 42.1% | 0.4262793291031878 | $-1.92 | -0.770% | 0.924% |
| S50_london_sideline_fade | validation | base | 40 | 52.5% | 0.7939297675008363 | $-1.41 | -0.565% | 1.260% |
| S50_london_sideline_fade | validation | stress | 23 | 43.5% | 0.5026130275900391 | $-2.31 | -0.924% | 1.449% |
| S50_london_sideline_fade | validation | severe | 10 | 50.0% | 0.7181863759485677 | $-0.44 | -0.174% | 0.535% |

- Decyzja dla `S50_london_sideline_fade`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 108, 'validation': 58}.
- Udział reżimów 5m: {'UP': 0.299, 'DOWN': 0.284, 'SIDELINE': 0.417}.

Kapitał $250, jeden wspólny rachunek SOL+XRP. Base 5/2 bps, stress 8/5, severe 10/10. Okno ograniczone do cache lokalnego. To nie jest strojenie S49 po wynikach.
