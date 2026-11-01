# S67 — dual-slot NY ORB + 1h Donchian/ADX, cel $5/dzień

Hash protokołu: `222f94758ab45434c6d5d5466a19c3d1ca3980e765a03dfed5ae429496ca3bec`.

Dwa sloty (SOL i XRP naraz), ryzyko $15. NY ORB 13:00-14:00 UTC hold do wieczora. 1h Donchian-10 tylko przy ADX>=25, bez capu 2.5R. To nie jest S49 ani S55.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | $/dzień | Max DD | mean R | $5? |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| S67_ny_orb_htc | development | base | 46 | 30.4% | 0.3473459537548001 | $-68.73 | $-0.45 | 28.411% | -0.425 | nie |
| S67_ny_orb_htc | development | stress | 34 | 26.5% | 0.27118694179561015 | $-67.89 | $-0.44 | 28.084% | -0.519 | nie |
| S67_ny_orb_htc | development | severe | 31 | 22.6% | 0.23514187001133632 | $-70.13 | $-0.46 | 28.721% | -0.554 | nie |
| S67_ny_orb_htc | validation | base | 45 | 31.1% | 0.6847579262090314 | $-39.82 | $-0.43 | 28.279% | -0.086 | nie |
| S67_ny_orb_htc | validation | stress | 42 | 31.0% | 0.6117023098753012 | $-48.84 | $-0.53 | 29.007% | -0.147 | nie |
| S67_ny_orb_htc | validation | severe | 36 | 27.8% | 0.541666507450263 | $-54.23 | $-0.59 | 28.795% | -0.221 | nie |

- Decyzja dla `S67_ny_orb_htc`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 164, 'validation': 107}.

| S67_hourly_donchian_adx | development | base | 24 | 8.3% | 0.5194989387124817 | $-40.30 | $-0.26 | 28.145% | -0.292 | nie |
| S67_hourly_donchian_adx | development | stress | 21 | 9.5% | 0.5434399853725528 | $-37.19 | $-0.24 | 28.361% | -0.253 | nie |
| S67_hourly_donchian_adx | development | severe | 19 | 10.5% | 0.5476964646454282 | $-37.92 | $-0.25 | 28.078% | -0.249 | nie |
| S67_hourly_donchian_adx | validation | base | 41 | 26.8% | 0.7908515906678661 | $-29.80 | $-0.32 | 28.941% | -0.048 | nie |
| S67_hourly_donchian_adx | validation | stress | 39 | 23.1% | 0.687399110344123 | $-46.83 | $-0.51 | 29.350% | -0.149 | nie |
| S67_hourly_donchian_adx | validation | severe | 37 | 24.3% | 0.680515790431898 | $-46.87 | $-0.51 | 28.458% | -0.168 | nie |

- Decyzja dla `S67_hourly_donchian_adx`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 203, 'validation': 104}.

Cel $5/dzień jest diagnostyką. Nie jest to zgoda na live.
