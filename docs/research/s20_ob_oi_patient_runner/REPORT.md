# S20 — S18 (OB + OI) z cierpliwym trend-runnerem (niski WR, duże R)

Hash zamrożonego protokołu: `ddda4bbe1794dd21042e04db795bcf3fe20fd61e2f37f323f9064991e0043b3b`.

To badanie retrospektywne. Jedyna zmiana względem S18 H1: aktywacja breakeven/trailingu później (+1.5R/+2.0R), szerszy trailing (2.5x/3.0x ATR), wyższy cap (8R/10R). Testuje odwrotny kierunek niż S19.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD MTM |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S20_ob_oi_patient_runner | development | base | 137 | 46.7% | 1.065910313367188 | $2.08 | 0.834% | 4.485% |
| S20_ob_oi_patient_runner | development | stress | 139 | 42.4% | 0.7641887117529381 | $-7.74 | -3.095% | 4.860% |
| S20_ob_oi_patient_runner | development | severe | 119 | 34.5% | 0.43738912962342813 | $-14.89 | -5.955% | 6.011% |
| S20_ob_oi_patient_runner | validation | base | 43 | 48.8% | 1.1168621537431267 | $1.04 | 0.417% | 1.789% |
| S20_ob_oi_patient_runner | validation | stress | 42 | 45.2% | 0.8567638736588723 | $-1.32 | -0.530% | 1.841% |
| S20_ob_oi_patient_runner | validation | severe | 44 | 40.9% | 0.36031409696635525 | $-6.70 | -2.681% | 2.880% |

- Decyzja dla `S20_ob_oi_patient_runner`: **REJECTED_AT_VALIDATION_GATE**.
- Surowe kandydaty per okno: {'development': 196, 'validation': 62, 'retrospective_evaluation': 158}.

| S20_ob_oi_very_patient_runner | development | base | 134 | 42.5% | 0.9831435484094329 | $-0.52 | -0.209% | 5.109% |
| S20_ob_oi_very_patient_runner | development | stress | 137 | 37.2% | 0.7667991450188562 | $-7.71 | -3.086% | 5.409% |
| S20_ob_oi_very_patient_runner | development | severe | 123 | 30.1% | 0.5192505727080413 | $-14.92 | -5.967% | 6.023% |

- Decyzja dla `S20_ob_oi_very_patient_runner`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Surowe kandydaty per okno: {'development': 196, 'validation': 62, 'retrospective_evaluation': 158}.

## Interpretacja

Trasa przegrywająca bramkę development nie jest strojona dalej ani wybierana jako „najmniej zła”. Niski win rate NIE jest tu traktowany jako porażka sam w sobie — liczy się PF/expectancy, dokładnie te same bramki co we wszystkich poprzednich protokołach.

Kapitał: $250; jeden wspólny cash/pending/position; stałe ryzyko $0,50; notional do $125; dźwignia do 5x. Base 2/5/2 bps (maker/taker/slippage), stress 5/8/5, severe 10/10/10.
