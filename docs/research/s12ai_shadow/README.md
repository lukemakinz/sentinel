# S12AI: X-of-Y → komitet AI → deterministyczne ryzyko

## Status

S12AI jest wdrożony wyłącznie jako domyślnie wyłączony tryb shadow. Nie może
pojawić się jako wykonywalny sygnał: kontekst ma `shadow_only=true`, rekord L2
jest automatycznie oznaczany jako `dismissed`, a wykonanie jest zablokowane w
ustawieniach.

## Przepływ decyzji

1. L1 buduje dziewięć niezależnych rodzin dowodów, zamiast liczyć każdy
   skorelowany wskaźnik jako osobny głos.
2. Kandydat trafia do AI po spełnieniu co najmniej 7/9, minimum 2/3 dowodów
   strukturalnych oraz wszystkich twardych warunków bezpieczeństwa.
3. Cztery role AI analizują ten sam zamrożony snapshot: trader ICT/SMC, order
   flow/quant, risk manager i devil's advocate.
4. Deterministyczny supervisor wymaga APPROVE z confidence >=60 od trzech
   rdzeniowych agentów. Mocne veto devil's advocate odrzuca setup.
5. L3 liczy geometrię niezależnie od werdyktu, aby w shadow można było porównać
   APPROVE z kontrfaktycznym wynikiem REJECT.
6. Po ośmiu godzinach resolver sprawdza zamknięte świece 1m i nadaje obu
   kohortom identyczną etykietę +1R/-1R. Przy nieznanej kolejności intrabar
   jednoczesny SL i TP jest zawsze liczony jako strata.

Identyczny strukturalny setup ma stabilny fingerprint, więc nie wywołuje modelu
ponownie przy każdym minutowym skanie. Sprawdzenie bazy jest uzupełnione atomową
24-godzinną blokadą kolejki w Redisie, aby dwa nakładające się skany nie wysłały
tego samego kandydata przed zapisaniem pierwszej decyzji.

Agent risk-manager dostaje odczytany w chwili decyzji snapshot: dzienny i
tygodniowy PnL, serie strat, aktywne kill-switche, liczbę pozycji oraz equity.
Brak snapshotu nie jest zastępowany wymyślonymi wartościami.

## Co mówi backtest kolejki, a czego nie mówi

Na development maj–czerwiec 2026 przetestowano trzy wcześniej zamrożone progi.
Zakładano, że agent zatwierdza każdy kandydat:

| Quorum | Fille | WR | PF | Zwrot |
|---|---:|---:|---:|---:|
| 7/9, struktura 2/3 | 125 | 20,8% | 0,166 | -6,273% |
| 7/9, struktura 3/3 | 91 | 18,7% | 0,104 | -4,930% |
| 8/9, struktura 3/3 | 66 | 13,6% | 0,068 | -3,943% |

Żaden wariant nie przeszedł warunku PF > 1 i dodatniego PnL. Lipiec–sierpień
nie został otwarty do wyboru progu. Samo X-of-Y **nie tworzy przewagi**; tworzy
jedynie kolejkę przypadków do oceny.

Przy najlepszym surowym PF agent musiałby usunąć ponad 83,4% wartości strat,
zachowując wszystkie zyski, aby dojść zaledwie do PF > 1. Tego nie wolno
zakładać bez prospektywnego dowodu.

## Warunek uznania wartości AI

Po zamrożeniu progu, promptów i wersji modelu należy zebrać minimum 100
rozstrzygniętych kandydatów. Dla każdego trzeba zapisać ten sam entry, SL, TP i
koszty niezależnie od APPROVE/REJECT. AI przechodzi dopiero wtedy, gdy:

- kohorta APPROVE ma PF > 1,20 po kosztach i dodatni wynik;
- kohorta APPROVE ma mniejsze DD niż approve-all;
- kontrfaktyczna kohorta REJECT jest wyraźnie gorsza od APPROVE;
- wynik pozostaje dodatni w kosztach stress;
- żaden błąd/brak odpowiedzi agenta nie zamienia się w APPROVE.

Aktualnie na hoście nie ma skonfigurowanego klucza Anthropic ani OpenAI, więc
nie istnieją jeszcze prawdziwe werdykty, które można uczciwie ocenić.
