# Sentinel — plan działania (2026-10-29)

Cel: najpierw dowód przewagi na danych poza próbką, potem egzekucja, potem kapitał.
Raportujemy $/dzień (i dystans do $5/dzień) **oraz** zwrot/DD; skalowanie wg zwrotu/DD.
Aktualny opis strategii i architektury do przekazania dalej:
`docs/STRATEGIE_I_DZIALANIE_APKI_COPY_PASTE.md`.

## Teraz

| # | Krok | Kryterium „gotowe” |
|---|---|---|
| ✅ 1 | Archiwum order booka i aggTrade przed pruningiem (Parquet, manifest, sha256, raport luk) | prune usuwa tylko dni z poprawnym archiwum |
| ✅ 2 | Test OOS 2026-09-01 → ostatnia pełna doba: zamrożone Book A, FCM_SAFE25, BENCH_AB_R2 + Deflated Sharpe (liczba prób = liczba badań) | raport w `docs/research/oos_2026_09_10/` |
| ✅ 3 | Deterministyczna bramka kandydatów przed OpenAI | AI wołane tylko dla kandydata; testy; koszt/dzień w raporcie |
| ✅ 4 | Integralność pomiaru AI | jeden epizod kandydata i jeden outcome baseline; PASS/WAIT AI = 0 PnL; brak pompowania próby przez kolejne bary |
| ✅ 5 | Izolacja paper/live | PaperTradingEngine nie dotyka mirrorów giełdowych; EOD wysyła wyłącznie `reduceOnly` albo przechodzi w HALT; niezależny `risk_watchdog` nadzoruje feed/drawdown oraz cykliczny sync giełdy, gdy live jest włączony |
| ✅ T | Trend State v1 + prospektywne M0/M1/M2/M3 | 5m/15m/1h/4h/1d oraz Global Context v1.3; jeden outcome, terminalne no-trade = 0R, osobno brak danych M3 i globalne veto |
| ✅ L | Post-mortem i kontrfakty shadow | v3: diagnoza + market 1R/1,5R/2R, limit 5m oraz day-tradingowe P1/P2 (partiale, BE, risk-cut, runner trailing) na tych samych świecach; dashboard; bez autostrojenia |
| ✅ P | Uniwersalny Strategy Plugin Engine v1 | auto-discovery modułów, wersjonowany kontrakt danych/stref/triggera, aktywacja przez konfigurację, bezpieczne wyłączanie z zachowaniem replay; rdzeń nie zna ID strategii |

## Następnie

6. ✅ Silnik ekspozycji portfela (bety z danych, netto ze znakiem, ryzyko do stopów) + stany NORMAL…HALT. Każde live entry ma trwałą intencję `PREPARED` zapisaną przed POST, deterministyczny `clientOid`, dokładną ilość po zaokrągleniu i odzyskanie niejednoznacznego submitu wyłącznie przez lookup; jedna aktywna intencja na symbol, a `PREPARED`/`UNCERTAIN` lub inna rozbieżność wymusza HALT.
7. 🟡 Kod stopów katastroficznych i `reduceOnly` KuCoin gotowy: wejście + stop atomowo przez `/api/v1/st-orders`, zamknięcie przez `/api/v1/orders`, kontrola aktywnego stopa przy każdym syncu. Read-only preflight sprawdza też nierozstrzygnięte intencje, pending orders i zgodność pozycji. Pozostała weryfikacja schematu odpowiedzi i restartu na testowym subkoncie; do tego czasu `EXCHANGE_SIDE_STOPS_IMPLEMENTED=False` i live jest twardo zablokowany.
8. ✅ Kontrfaktyczne bliźniaki w shadow: market vs limit oraz zamrożone P1/P2;
   replay `auction-replay-v1.2` na SOL 2024–09.2026 odrzucił oba dla M0
   (P1 −0,928R/trade, P2 −0,952R). Nie stroić dalej na M0; używać niezmienionych
   polityk dopiero z nowymi wejściami Intraday v2.
9. Zaimplementować trzy prerejestrowane pluginy `SENTINEL_INTRADAY_V2`
   (trend pullback, session expansion, range failed auction) z naturalnym stopem
   0,40–1,25%, kosztem stress ≤0,25R, hold ≤4h i bez overnight.
10. `ALT_BREADTH_BINANCE` z historycznym składem koszyka; test, czy poprawia Book A.
11. Rejestr hipotez z budżetem (1–2/mies.) i Deflated Sharpe w każdym raporcie.
12. ✅ Codzienny paper-forward z CLI i pętli ingestera; pierwszy ledger: 2026-10-27, 1 dzień, `INSUFFICIENT`, $0,00. Composite Book A+B nie może być promowany, dopóki Book B łamie limit 0,5% ryzyka.
13. ✅ S114 zamknięty na pełnym point-in-time universe 48/48: STRICT, EXTERNAL i ABSORB_CVD `REJECTED`; bez kolejnych retrospektywnych wariantów tej rodziny.

## Później (gdy będą setki oznaczonych przypadków)

ML meta-labeling (nie LLM), analogi historyczne, wektor stanu rynku; mikro-live po
sprawdzeniu minimalnych wielkości zleceń KuCoin; Raspberry Pi jako środowisko docelowe.

## Zasady

- AI: asystent (ocena kandydatów w shadow, post-mortem, research), nigdy kierunek, SL ani wielkość pozycji.
- Każda zmiana strategii: hipoteza → zamrożony protokół → nowe dane → decyzja człowieka.
- Gotówka/PASS jest pełnoprawną decyzją.
