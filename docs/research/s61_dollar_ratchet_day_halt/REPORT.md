# S61 — dollar-ratchet trail + day halt po serii strat

Hash protokołu: `74ab5d99f027c2ca1d059b9557834f15f970c50963e8de791d45666bde00165a`.

Ten sam sygnał S60 15m. Wypłata: po 1R stop jedzie za dolarem (blokada 50% szczytowego open $), cap 8R. Po 2 stratach z rzędu koniec dnia (`all`) albo koniec shortów (`short`). Charakterystyka S60-informed, nie zgoda na live.

| Trasa | Okno | Scenariusz | Fille | WR | PF | PnL | Zwrot | Max DD | mean R |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ratchet_all | development | base | 74 | 54.1% | 0.8737154411411309 | $-1.91 | -0.764% | 1.858% | -0.055 |
| ratchet_all | development | stress | 74 | 50.0% | 0.5795231485198205 | $-6.84 | -2.737% | 2.914% | -0.187 |
| ratchet_all | development | severe | 74 | 45.9% | 0.36630509705522624 | $-10.51 | -4.203% | 4.296% | -0.302 |
| ratchet_all | validation | base | 27 | 51.9% | 0.5583960786564403 | $-2.62 | -1.046% | 1.747% | -0.194 |
| ratchet_all | validation | stress | 27 | 44.4% | 0.3667532206932574 | $-3.97 | -1.587% | 2.109% | -0.296 |
| ratchet_all | validation | severe | 27 | 33.3% | 0.12821645283019434 | $-5.63 | -2.252% | 2.304% | -0.421 |

- Decyzja dla `ratchet_all`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 83, 'validation': 29}.
- Halt diagnostics: {'development': 1, 'validation': 0}.

| ratchet_short | development | base | 75 | 54.7% | 0.8799982054283816 | $-1.81 | -0.726% | 1.858% | -0.052 |
| ratchet_short | development | stress | 75 | 50.7% | 0.633410106774444 | $-5.97 | -2.387% | 2.914% | -0.160 |
| ratchet_short | development | severe | 75 | 46.7% | 0.38904263660541855 | $-10.28 | -4.111% | 4.204% | -0.280 |
| ratchet_short | validation | base | 27 | 51.9% | 0.5583960786564403 | $-2.62 | -1.046% | 1.747% | -0.194 |
| ratchet_short | validation | stress | 27 | 44.4% | 0.3667532206932574 | $-3.97 | -1.587% | 2.109% | -0.296 |
| ratchet_short | validation | severe | 27 | 33.3% | 0.12821645283019434 | $-5.63 | -2.252% | 2.304% | -0.421 |

- Decyzja dla `ratchet_short`: **REJECTED_AT_DEVELOPMENT_GATE**.
- Kandydaty surowe: {'development': 83, 'validation': 29}.
- Halt diagnostics: {'development': 0, 'validation': 0}.

