# Sentinel — plan działania (2026-10-27)

Cel: najpierw dowód przewagi na danych poza próbką, potem egzekucja, potem kapitał.
Raportujemy $/dzień (i dystans do $5/dzień) **oraz** zwrot/DD; skalowanie wg zwrotu/DD.

## Teraz

| # | Krok | Kryterium „gotowe” |
|---|---|---|
| 1 | Archiwum order booka i aggTrade przed pruningiem (Parquet, manifest, sha256, raport luk) | prune usuwa tylko dni z poprawnym archiwum |
| 2 | Test OOS 2026-09-01 → ostatnia pełna doba: zamrożone Book A, FCM_SAFE25, BENCH_AB_R2 + Deflated Sharpe (liczba prób = liczba badań) | raport w `docs/research/oos_2026_09_10/` |
| 3 | Deterministyczna bramka kandydatów przed OpenAI | AI wołane tylko dla kandydata; testy; koszt/dzień w raporcie |

## Następnie

4. Silnik ekspozycji portfela (alty = zakład na BTC) + stany NORMAL/CAUTION/CLOSE_ONLY/HALT, idempotentne zlecenia, rekoncyliacja.
5. Kontrfaktyczne bliźniaki w shadow (market vs limit; P1/P2 po implementacji w resolverze).
6. `ALT_BREADTH_BINANCE` z historycznym składem koszyka; test, czy poprawia Book A.
7. Rejestr hipotez z budżetem (1–2/mies.) i Deflated Sharpe w każdym raporcie.
8. Codzienny paper-forward z CLI (Book A, FCM).

## Później (gdy będą setki oznaczonych przypadków)

ML meta-labeling (nie LLM), analogi historyczne, wektor stanu rynku; mikro-live po
sprawdzeniu minimalnych wielkości zleceń KuCoin; Raspberry Pi jako środowisko docelowe.

## Zasady

- AI: asystent (ocena kandydatów w shadow, post-mortem, research), nigdy kierunek, SL ani wielkość pozycji.
- Każda zmiana strategii: hipoteza → zamrożony protokół → nowe dane → decyzja człowieka.
- Gotówka/PASS jest pełnoprawną decyzją.
