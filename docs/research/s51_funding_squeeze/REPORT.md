# S51 — fade crowded funding squeeze

Hash protokołu: `07cc4e1c247bd6349161c9320882a512b3d40e2916051921c888bcbdc8a5d148`.

Funding w ogonie 14 dni (42 settl.) + 15m rejection. Jedna próba na settlement. Target 1.0R, time-stop 120 min, bez trailing. To nie jest S46 (veto na OB) ani strojenie S49/S50.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S51_crowded_fade | development | base | 158 | 41.1% | 0.502020589731787 | $-15.10 | -6.040% | 6.040% |
| S51_crowded_fade | development | stress | 143 | 42.0% | 0.41607498021590367 | $-15.10 | -6.040% | 6.040% |
| S51_crowded_fade | development | severe | 74 | 41.9% | 0.3624677675270537 | $-10.34 | -4.137% | 4.497% |
| S51_crowded_fade | validation | base | 101 | 50.5% | 0.6809814391523161 | $-6.98 | -2.792% | 3.482% |
| S51_crowded_fade | validation | stress | 55 | 43.6% | 0.5266465291579099 | $-6.13 | -2.453% | 2.884% |
| S51_crowded_fade | validation | severe | 32 | 40.6% | 0.4134272219351486 | $-4.79 | -1.915% | 2.542% |

- Decyzja dla `S51_crowded_fade`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 386, 'validation': 147}.
- Udział reżimów 15m: {'UP': 0.299, 'DOWN': 0.284, 'SIDELINE': 0.417}.

| S51_crowded_fade_sideline | development | base | 109 | 36.7% | 0.35519477163697827 | $-15.00 | -5.999% | 6.093% |
| S51_crowded_fade_sideline | development | stress | 86 | 36.0% | 0.3095546191291179 | $-13.06 | -5.225% | 5.225% |
| S51_crowded_fade_sideline | development | severe | 39 | 30.8% | 0.2962678762230016 | $-7.52 | -3.007% | 3.685% |
| S51_crowded_fade_sideline | validation | base | 53 | 52.8% | 0.690982140425417 | $-3.39 | -1.355% | 2.519% |
| S51_crowded_fade_sideline | validation | stress | 26 | 38.5% | 0.3946629093786662 | $-4.19 | -1.676% | 1.963% |
| S51_crowded_fade_sideline | validation | severe | 15 | 33.3% | 0.2963308631367638 | $-3.08 | -1.234% | 1.601% |

- Decyzja dla `S51_crowded_fade_sideline`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 197, 'validation': 77}.
- Udział reżimów 15m: {'UP': 0.299, 'DOWN': 0.284, 'SIDELINE': 0.417}.

Kapitał $250, jeden wspólny rachunek SOL+XRP. Base 5/2 bps, stress 8/5, severe 10/10. Okno ograniczone do cache lokalnego.
