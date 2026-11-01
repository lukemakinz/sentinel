# S114 — wyniki częściowe (21 z 48 symboli), przebieg wstrzymany 2026-10-27

**To nie jest werdykt protokołu** — ten wymaga wszystkich 48 symboli. Przebieg
zatrzymano na prośbę użytkownika; 21 symboli przeliczono ponownie z cache
(skrypt ad hoc, ta sama funkcja `_symbol_job` i `_stats` z runnera).

Symbole: SUI, FARTCOIN, 1000PEPE, TRUMP, ENA, LAYER, WIF, CRV, EOS (dane do
2025-05-21), ONDO, AAVE, TAO, OM (handel do 2026-02-23, poprawka AMENDMENT.md),
FIL, TRX, NEAR, 1000SHIB, MUBARAK, HBAR, POPCAT, WLD. Wykluczeń: 0.

Konta $250 / symbol, ryzyko 0,2% ($0,50 / transakcja), wynik w R.

## Koszty stress, całość 2025-05 → 2026-09

| Trasa | Transakcje | WR | PF (R) | Średnio R | Suma R | PnL |
|---|---:|---:|---:|---:|---:|---:|
| STRICT | 4 | 0% | 0,00 | −1,000 | −4,0 | −$2,00 |
| EXTERNAL | 592 | 18,8% | 0,68 | −0,263 | −155,5 | −$76,83 |
| ABSORB_CVD | 108 | 22,2% | 0,86 | −0,106 | −11,5 | −$5,55 |

## Średnie R w oknach (stress, liczba transakcji)

| Trasa | development | validation | retrospective eval |
|---|---:|---:|---:|
| EXTERNAL | −0,161 (186) | −0,328 (228) | −0,285 (178) |
| ABSORB_CVD | −0,230 (36) | −0,139 (44) | +0,104 (28) |

## Inne

- EXTERNAL base: −0,190 R (607); severe: −0,337 R. Long −0,237 R (326), short −0,294 R (266).
- ABSORB_CVD base: −0,030 R (110); severe: −0,202 R. Long −0,096 R (57), short −0,118 R (51).
- Udział najlepszego symbolu w dodatnim R: EXTERNAL 55% (HBAR), ABSORB_CVD 34% (FARTCOIN).
- STRICT: reguła „RR ≥ 1:3 do najbliższego BSL” prawie nie występuje (4 transakcje / 16 mies.).
