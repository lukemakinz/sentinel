# Sentinel — stan na 27.10.2026

Dokument do wznowienia prac. Branch: `auction-intelligence` (16 commitów ponad `main`,
nic nie wypchnięte ani nie zmergowane). Plan bieżący: `docs/ACTION_PLAN.md`.
Instrukcja Pi/Telegram: `docs/PI_TELEGRAM_RUNBOOK.md`.
Samodzielny opis strategii i działania aplikacji, gotowy do skopiowania:
`docs/STRATEGIE_I_DZIALANIE_APKI_COPY_PASTE.md`.

## Aktualizacja 28.10.2026 — audyt integralności i bezpieczeństwa

- AI i baseline są łączone przez jeden `AuctionCandidate`; kolejne bary tego samego
  epizodu nie tworzą dodatkowych outcome planów. PASS/WAIT AI jest liczony jako
  0 PnL na tym samym wyniku kontrfaktycznym baseline.
- TTL na wejście i maksymalny czas utrzymania po triggerze są rozdzielone.
- `PaperTradingEngine` nie obsługuje pozycji `source=exchange`; nocna pozycja
  giełdowa, której system nie potrafi rzeczywiście zamknąć, powoduje HALT.
- Watchdog feedu/drawdownu działa jako osobna usługa `risk_watchdog`, niezależnie
  od Telegrama. Gdy live jest włączony, co cykl wykonuje również sync i
  rekoncyliację KuCoin; utrata widoczności konta/pozycji/zleceń wymusza ręcznie
  odblokowywany `CLOSE_ONLY`. Stan handlu został skonsolidowany do blokowanego
  singletonu.
- Kontrakty KuCoin są zaokrąglane wyłącznie w dół; ilość poniżej jednego kontraktu
  jest odrzucana. Transfer rezerwy jest ograniczony do udziału w zysku ponad
  `LIVE_CAPITAL_BASELINE_USD`.
- Paper-forward ma statusy `INSUFFICIENT/OBSERVE/ON_TRACK`, blokadę rewizji danych
  i minimum 90 dni; composite A+B pozostaje niepromowalny przez ryzyko Book B.
- Duże replaye (`results.json`, `*.json.gz`, Parquet) są poza Git; protokoły,
  hashe, manifesty, summary i raporty pozostają wersjonowane.

## Aktualizacja 29.10.2026 — egzekucja ochronna KuCoin

- Live entry nie ma już ścieżki bez stopa: adapter wysyła wejście i katastroficzny
  SL atomowo przez KuCoin Futures `/api/v1/st-orders`; brak, błędna strona lub
  nienumeryczna cena stopa kończą się odmową przed wywołaniem API.
- Zamknięcie pozycji giełdowej jest zleceniem market po przeciwnej stronie z
  `reduceOnly=true`; lokalny mirror pozostaje OPEN, dopóki kolejny sync nie potwierdzi
  zamknięcia. Nie ma „papierowego” zamykania pozycji z giełdy.
- Sync pobiera osobno aktywne stop orders. Otwarta pozycja bez aktywnego,
  przeciwnego i redukującego ekspozycję stopa albo błąd odczytu stopów powoduje HALT.
- HTTP 2xx nie wystarcza do uznania zlecenia za przyjęte: wymagany jest także kod
  aplikacyjny KuCoin `200000`; timeout i niejednoznaczna odpowiedź kończą się fail-closed.
- Mutacje wymagają deterministycznego `clientOid`. Po timeout/5xx adapter nie ponawia
  wejścia: odczytuje `/api/v1/orders/byClientOid` (także dla stop order), a brak
  jednoznacznego dopasowania wymusza HALT i ręczną rekoncyliację.
- Dokładna intencja live (`clientOid`, kierunek, stop i ilość po zaokrągleniu) jest
  zapisywana jako `PREPARED` **przed** pierwszym POST. Restart nigdy nie wysyła jej
  ponownie w ciemno: wykonuje tylko lookup; status niejednoznaczny zostaje
  `UNCERTAIN`. Baza dopuszcza jedną aktywną intencję na symbol. Cykliczny sync nie
  może sam „uzdrowić” `PREPARED`/`UNCERTAIN` na podstawie podobnej pozycji — wymusza
  HALT, dopóki wynik nie zostanie udowodniony przez `clientOid`.
- Paper-forward rozróżnia brak publikacji od awarii sieci, korzysta z lokalnych archiwów
  z checksumami i ponawia tani probe co godzinę aż pojawi się wczorajsza pełna doba.
  Ten sam zakres zwraca zapisany ledger bez ponownego dwuletniego replayu.
- Implementacja jest pokryta testami lokalnymi, lecz **niezweryfikowana na koncie**.
  `EXCHANGE_SIDE_STOPS_IMPLEMENTED=False` pozostaje twardą blokadą live do testu na
  odseparowanym subkoncie i kontroli zachowania po restarcie.
- `manage.py kucoin_preflight` wykonuje wyłącznie odczyty i kontroluje poświadczenia,
  endpointy, ochronę pozycji, lokalne intencje, pending `clientOid` oraz zgodność
  lokalnych pozycji z giełdą. `PREPARED`/`UNCERTAIN` i każda niewyjaśniona pozycja
  blokują wynik „OK”.

---

## 1. Najważniejsze wnioski

1. **Jedyny kandydat z dowodem poza próbką to BENCH_AB_R2 (Book A + Book B).**
   Na danych, których nie dotknęło żadne badanie (2026-09-01 → 10-26, 56 dni):
   stress **+$15,43 na $500, $0,275/dzień, max DD 1,84%** (Book A +$11,06, Book B
   +$4,37 z 5 transakcji). Wrzesień +$19,71, październik ok. −$4,28.
   Po korekcie na 133 wcześniejsze próby **DSR = 0,02** — wynik nie jest istotny
   statystycznie; test mógł strategię obalić, nie potwierdzić.
2. **Realistyczne koszty Book A są w porządku.** Funding (KuCoin ≈ 1,6× Binance)
   i zaokrąglanie do kontraktów KuCoin zabierają tylko ok. 1–5% wyniku (Book A
   trzyma dużo gotówki). Przy $250: OOS $10,62 zamiast $11,06.
3. **Book A nie skaluje się liniowo**: $/dzień na każde $250 spada przy $500 i
   $1000 (filtr minimalnej pozycji $15 dopuszcza więcej małych, słabych pozycji).
4. **Book B jest niezgodny z nowymi limitami ryzyka**: stałe $6 ryzyka = 1,2% z
   $500, a limit otwartego ryzyka portfela to 0,5%. Na KuCoin to 2–4 kontrakty
   BTC → błąd wielkości pozycji 12–18% (maks. ~20%).
5. **Strategia ze screenów (OB Liquidity Reversal / ICT-SMC) nie ma przewagi**:
   - S112 (8 dużych rynków): STRICT 0 transakcji, EXTERNAL PF 0,82, −0,139 R.
   - S113 (12 rynków, held-out): absorpcja ≈ 0 R (PF 1,00, 44 tr.), partial 2R gorzej.
   - S114 (pełne 48/48 alt mid-cap, 0 wykluczeń i 0 błędów okien): EXTERNAL stress
     **−0,239 R / 1339 tr.**, ABSORB_CVD stress **−0,124 R / 248 tr.**,
     STRICT stress −0,708 R / 7 tr. Wszystkie trasy formalnie `REJECTED`.
     ABSORB_CVD poprawia wynik, ale nie daje przewagi: nawet pooled base to −0,021 R,
     a validation stress −0,251 R.
   - Reguła „RR ≥ 1:3 do najbliższego BSL” prawie nigdy nie występuje na płynnych rynkach.
   - **Filtr absorpcji (CVD/OI) konsekwentnie poprawia wynik**, ale nie wyprowadza go nad zero.
6. **Cała rodzina intraday price-action (S7–S114, ~20 badań) jest na minusie.**
   Dalsze warianty na tych samych danych = ryzyko dopasowania do szumu.
7. **Cel $5/dzień przy $250 = 2%/dzień — nierealny.** Przy realistycznych 10–20%/rok
   wymaga ok. $9–18 tys. kapitału. Dziś: ok. $0,05–0,10/dzień przy $250
   (brakuje ok. $4,90–4,95/dzień).
8. **AI to asystent, nie trader.** Bez udowodnionej przewagi wybór strategii przez
   LLM nic nie da; mierzymy AI vs mechaniczny baseline na tym samym strumieniu kandydatów.
9. Ceny KuCoin ≈ Binance (mediana < 1,3 bps, korelacja ≥ 0,998) — testy na danych
   Binance przenoszą się cenowo na KuCoin.
10. Bety do BTC liczone z danych (ETH 1,38, SOL 1,41) są ~40% wyższe od starej stałej
    tabeli (0,90/0,85) — dawne „portfolio heat” zaniżało ryzyko altów.

---

## 2. Co zostało zrobione (zacommitowane)

| Obszar | Co działa | Gdzie |
|---|---|---|
| Koszt analizy AI | koszt każdej analizy OpenAI na końcu wyniku, dzienny limit $1, zapłacone-ale-odrzucone odpowiedzi liczone, deduplikacja nie liczy podwójnie | `l2_agents/auction_*.py` |
| Bramka AI | OpenAI wołane tylko dla kandydata mechanicznego; ARM musi potwierdzić kandydata bez zmian; ten sam kandydat max raz / 4h; prompt `v2-candidate` | `l2_agents/auction_service.py` |
| Mechaniczny baseline | tor kontrolny bez AI na tych samych snapshotach; raport `paired_comparison` | `l2_agents/mechanical_baseline.py` |
| Setup search | skaner 60 altów Binance wg checklisty 7 pkt (LONG + lustrzany SHORT), statusy WAIT_RETEST / WAIT_MSS / WAIT_SWEEP / … z instrukcją „co dalej” | `manage.py setup_search`, `l1_filter/setup_search.py` |
| Dziennik setupów | zapis co 15 min, rozliczanie TP1/SL/czas/wygaśnięcie (stress R), epizody sweep→MSS | `l1_filter/setup_journal.py` |
| Telegram | `/status /scan /raport /koszt /paper /pauza /wznow /stop`, alerty WAIT_RETEST/WAIT_MSS, watchdog feedu (osobny proces), podsumowanie 07:00 UTC | `telegram_bot/` |
| Stany handlu | NORMAL→CAUTION→DEFENSIVE→CLOSE_ONLY→HALT; system tylko podnosi; HALT po DD ≥ 10% / rozbieżności z giełdą odblokowuje tylko CLI | `risk/trading_state.py`, `manage.py trading_state` |
| Ekspozycja portfela | beta z danych 1h/30d, beta netto ze znakiem, ryzyko do stopów; limity 0,5% / ±1,5× / 3× w `RiskManager` | `risk/exposure.py` |
| Bezpieczeństwo live | trwała intencja przed POST, atomowe entry+SL KuCoin, `reduceOnly` close, kontrola aktywnych stopów, rekoncyliacja → HALT, deterministyczny `clientOid`; **live nadal zablokowany do testu subkonta** (`EXCHANGE_SIDE_STOPS_IMPLEMENTED = False`) | `executor/live_execution.py`, `executor/exchange_adapters.py`, `executor/reconcile.py`, `executor/tasks.py` |
| Archiwum danych | order book + aggTrade → Parquet (zstd) dziennie, manifest + sha256 + raport luk; pruning usuwa tylko zweryfikowane dni | `ingester/archive.py`, `manage.py archive_market_data --verify` |
| Pętle ingestera | feed, OI, shadow (5 min), setup search (15 min), próg wieloryba (1h), archiwum+pruning (02:00 UTC), paper-forward (≥03:00 UTC) — bez Celery | `ingester/binance_ws.py` |
| Test OOS | zamrożony BENCH_AB_R2 na 09–10.2026, PSR/DSR | `backtest/run_oos_2026_09_10.py`, `docs/research/oos_2026_09_10/` |
| Paper-forward | codzienny przelicznik od 2026-10-27, ledger, wykrywanie rewizji danych, status wg zamrożonych reguł | `manage.py paper_forward`, `docs/research/paper_forward_bench_ab_r2/protocol.json` |
| Realizm Book A | opcjonalny funding i zaokrąglanie do kontraktów w symulatorze | `backtest/run_book_a_execution_realism.py` |
| Badania | S112, S113 (+ symulator z partial), Deflated Sharpe | `backtest/`, `docs/research/` |
| Pi | `Dockerfile.pi` (kontekst budowania naprawiony), `.dockerignore`, TA-Lib + pyarrow jako koła aarch64, Celery opcjonalne (profil), usługa `telegram_bot` | `docker-compose.pi.yml`, `deploy-pi.sh` |

Testy: **883 OK** (`manage.py test`).

## 3. Zrobione, ale NIEZACOMMITOWANE (na dysku)

- `backend/l1_filter/setup_search.py` — cechy setupu (głębokość sweepu, displacement,
  FVG, stop, wiek strefy, godzina MSS, discount 4H) + kontekst rynku (BTC nad EMA50 1h,
  zwrot 24h, breadth altów).
- `backend/l1_filter/setup_journal.py` — 9 wariantów kontrfaktycznych
  (wejście: krawędź FVG / środek FVG / market po MSS × wyjście: TP1 / pierwsze BSL ≥ 3R /
  partial 50% przy 2R), zamrażanie cech z chwili pierwszego zauważenia.
- `backend/l1_filter/tests/test_setup_journal.py`, `backend/telegram_bot/commands.py`
  (warianty w `/raport`).
- `backend/backtest/broad_universe.py`, `backend/backtest/run_s114_ob_reversal_broad_alts.py`
  (S114: uniwersum point-in-time z bucketu Binance, obsługa wycofanych i martwych rynków).
- `docs/research/` w całości poza repo (protokoły z hashami, raporty, wyniki).

Testy dla tych zmian przechodzą; brakuje commita.

## 4. Czego NIE zrobiono / co jest otwarte

| Pozycja | Stan | Blokada |
|---|---|---|
| S114 pełny werdykt (48 symboli) | **zakończony: wszystkie trasy REJECTED** | raport i summary w `docs/research/s114_ob_reversal_broad_alts/` |
| Stopy po stronie giełdy KuCoin | kod gotowy, live zablokowany | weryfikacja `/api/v1/st-orders` i listy stopów na subkoncie |
| `reduceOnly` close KuCoin | kod + testy lokalne gotowe | bezpieczny test z minimalnym kontraktem na subkoncie |
| Weryfikacja live (sync, rekoncyliacja, restart) | nie | klucz KuCoin (najpierw read-only, potem odseparowane subkonto) |
| Telegram na telefonie | kod gotowy | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` w `.env`, uruchomić `manage.py run_telegram_bot` |
| Tor AI w shadow | kod gotowy | brak środków na koncie OpenAI (429 insufficient_quota) |
| Build obrazu Pi | nieprzetestowany | Docker Desktop wyłączony / pierwsze uruchomienie na Pi |
| Autostart na Macu | ingester i watchdog w odłączonych sesjach `screen`, PID-y w `~/Library/Logs/sentinel/` | `screen` przeżywa zamknięcie sesji Codex, ale nie restart Maca; launchd blokowany przez TCC (`~/Desktop`); Pi jest docelowe |
| Limit ryzyka Book A oparty na zmienności | nie | Book A nie ma stopów → „ryzyko do stopu” go nie opisuje |
| Book B zgodny z limitami | nie | obniżenie ryzyka B = nowa strategia → osobne zamrożone badanie |
| `ALT_BREADTH_BINANCE` + test na Book A | nie | — |
| Rejestr hipotez z budżetem | nie | — |
| Przyciski „wziąłbym / nie” w alertach Telegram | nie | najpierw działający bot |
| P1/P2 (zarządzanie stopem) w resolverze shadow | nie | w rejestrze dozwolone tylko P0 |
| pytest w repo | nie skonfigurowany | wymaga `pytest-django`; runner to `manage.py test` |

## 5. Co jest do poprawy (znane słabości)

- **Statystyka**: 56 dni OOS to za mało; paper-forward potrzebuje ≥ 30 dni na status,
  ≥ 90 dni ON_TRACK przed canary.
- **Kontekst w dzienniku**: setupy zapisane przed dzisiejszą zmianą mają kontekst
  rynku z chwili późniejszego skanu, nie z chwili setupu.
- **S114**: uniwersum to top-48 alt mid-cap (wszystkie > $20M obrotu/dzień) — prawdziwe
  mikro-capy (jak DOOD ze screenów) wciąż nieprzetestowane; absorpcja bez OI (tylko CVD).
- **Logowanie**: komunikaty INFO z pętli ingestera nie trafiają do logu (konfiguracja
  logowania) — trudniej potwierdzić działanie pętli bez bazy.
- **Stary pipeline L1→L2** (Celery Beat) woła agentów AI poza limitem budżetu — na Pi
  Celery jest wyłączone domyślnie; nie włączać bez przeglądu.
- **`process_signal`** importuje wyłączoną aplikację `consensus` — ścieżka martwa.
- **Funding KuCoin** w badaniu realizmu to mnożnik ×1,6 z 30 dni, nie historia.
- **Kanał KuCoin**: minimalna pozycja BTC ≈ $80 (1 kontrakt 0,001 BTC).

## 6. Działające w tle (lokalnie, Mac)

- Ingester (`run_ingester`): feed SOL + kontekst BTC/ETH, shadow, setup search co 15 min,
  archiwum, paper-forward. Odłączona sesja: `sentinel-ingester`; PID:
  `~/Library/Logs/sentinel/ingester.pid`.
- Niezależny `run_risk_watchdog --interval 60`: feed stale → CLOSE_ONLY, DD → HALT;
  po przyszłym włączeniu live także cykliczny sync/rekoncyliacja KuCoin.
  Odłączona sesja: `sentinel-watchdog`; PID:
  `~/Library/Logs/sentinel/risk_watchdog.pid`.
- Stan obu procesów: `screen -ls`. Sesje pozostają aktywne po zamknięciu Codex,
  ale po restarcie Maca trzeba uruchomić je ponownie.
- Paper-forward aktywny: ledger obejmuje pierwszą pełną dobę **2026-10-27**;
  status `INSUFFICIENT`, stress PnL $0,00, 0 transakcji (`manage.py paper_forward`).

## 7. Proponowana kolejność dalszych prac

1. Commit niezacommitowanych zmian (sekcja 3); duże replaye są ignorowane, a do Git
   trafiają protokoły, hashe, manifesty, summary i raporty.
2. Podłączyć Telegram (token) i doładować OpenAI ($10–20) — oba tory zaczynają zbierać dane.
3. Szlif strategii ze screenów **tylko na danych z przyszłości**: dziennik (cechy +
   9 wariantów) → po ~100 zamkniętych setupach analiza, który kontekst / wariant działa;
   przyciski „wziąłbym / nie” do pomiaru selekcji uznaniowej.
4. **Nie uruchamiać S115 ani dalszych wariantów ICT/SMC** bez nowych danych prospektywnych;
   pełny S114 formalnie zamyka tę retrospektywną rodzinę.
5. Najpierw read-only i minimalny test subkonta KuCoin: atomowy entry+SL, widoczność
   stopa po restarcie, `reduceOnly` close i rekoncyliacja. Dopiero potem można zmienić
   kodową bramkę `EXCHANGE_SIDE_STOPS_IMPLEMENTED`.
6. Canary (prawdziwe pieniądze w mikroskali) tylko z Book A: limit ryzyka oparty na
   zmienności, rebalans limitami (maker), po ≥ 90 dniach paper-forward ON_TRACK.
7. `ALT_BREADTH_BINANCE`, rejestr hipotez, przeniesienie na Raspberry Pi.

## 8. Szybkie komendy

```bash
cd backend
../env/bin/python manage.py setup_search                 # skaner altów
../env/bin/python manage.py paper_forward                # Book A+B forward
../env/bin/python manage.py auction_shadow_report        # AI vs baseline, koszty
../env/bin/python manage.py trading_state                # stan handlu
../env/bin/python manage.py archive_market_data --verify # archiwum danych
../env/bin/python manage.py kucoin_preflight              # tylko odczyt KuCoin
../env/bin/python manage.py run_telegram_bot             # bot (po ustawieniu tokena)
```
