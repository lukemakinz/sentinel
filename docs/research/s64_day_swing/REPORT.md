# S64 — day/swing, $10 risk, cel $10/dzień

Hash protokołu: `dc703e5d9cb23d90600147c902f0acb4a1d8afc35a1ee9d235ff88c135a69e71`.

Dwie zamrożone trasy, bez grida. Turtle-20 bez capu 2.5R (to nie S55/S58). Wybicie poprzedniego dnia z hold do sesji (to nie S49 1R/90m). Ryzyko $10, halt DD 25%, daily 10%, weekly 15%. Kapitał $250, SOL+XRP.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | $/dzień | Max DD | mean R |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| S64_daily_turtle_20 | development | base | 6 | 50.0% | 3.1122110916264742 | $42.35 | $0.28 | 15.673% | 0.540 |
| S64_daily_turtle_20 | development | stress | 6 | 50.0% | 3.0342626598264344 | $40.79 | $0.27 | 15.588% | 0.513 |
| S64_daily_turtle_20 | development | severe | 6 | 33.3% | 1.7129424026118585 | $21.29 | $0.14 | 16.227% | 0.198 |
| S64_daily_turtle_20 | validation | base | 1 | 100.0% | Infinity | $0.97 | $0.01 | 4.111% | 0.097 |
| S64_daily_turtle_20 | validation | stress | 1 | 100.0% | Infinity | $0.83 | $0.01 | 4.061% | 0.083 |
| S64_daily_turtle_20 | validation | severe | 1 | 100.0% | Infinity | $0.67 | $0.01 | 4.005% | 0.067 |

- Decyzja dla `S64_daily_turtle_20`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 27, 'validation': 13}.

| S64_prior_day_htc | development | base | 35 | 34.3% | 0.6794196934467985 | $-41.31 | $-0.27 | 23.473% | -0.118 |
| S64_prior_day_htc | development | stress | 35 | 34.3% | 0.626853959427031 | $-46.38 | $-0.30 | 24.003% | -0.168 |
| S64_prior_day_htc | development | severe | 33 | 33.3% | 0.534464541343055 | $-56.95 | $-0.37 | 25.237% | -0.245 |
| S64_prior_day_htc | validation | base | 19 | 36.8% | 0.584258380082702 | $-26.06 | $-0.28 | 18.822% | -0.152 |
| S64_prior_day_htc | validation | stress | 20 | 35.0% | 0.4814323419055755 | $-34.85 | $-0.38 | 19.842% | -0.232 |
| S64_prior_day_htc | validation | severe | 20 | 30.0% | 0.4468219854870563 | $-34.82 | $-0.38 | 19.178% | -0.270 |

- Decyzja dla `S64_prior_day_htc`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 41, 'validation': 21}.

Cel $10/dzień jest diagnostyką, nie bramką krawędzi. Nie jest to zgoda na live.
