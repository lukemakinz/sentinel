# Sentinel Strategy Plugin Engine v1

**Status:** zaimplementowany; shadow/research only. Silnik live pozostaje
twardo zablokowany.

## Cel

Sentinel nie może być zbiorem instrukcji `if strategy_id == ...` rozrzuconych
po aplikacji. Strategia jest wymiennym pluginem. Wspólny silnik odpowiada za:

- jakość i świeżość danych;
- wersjonowany snapshot rynku i Global Context;
- walidację uprawnień `PASS/WAIT/ARM`;
- koszty, ryzyko, limity portfela i blokady;
- P0/P1/P2, replay, shadow, post-mortem i raportowanie;
- twardy brak prawa AI do składania zleceń.

Plugin strategii odpowiada wyłącznie za:

- metadane i wersję hipotezy;
- wymagane interwały oraz kompatybilne polityki zarządzania;
- dozwolone rodzaje stref osobno dla LONG i SHORT;
- opcjonalny, przyczynowy skaner kandydatów;
- deterministyczny trigger na zamkniętej świecy.

## Przepływ

```text
dane -> wspólny snapshot -> plugin.scan()
     -> wspólne bramki ekonomii/ryzyka
     -> opcjonalny recenzent AI: PASS / WAIT / ARM
     -> plugin.triggered() na zamkniętym 1m
     -> wspólne P0/P1/P2 + koszty + expiry/EOD
     -> wspólny outcome, replay i post-mortem
```

AI nie jest pluginem strategii i nie może podmienić kandydata. Jest recenzentem
między deterministycznym kandydatem a deterministycznym wykonaniem shadow.

## Stabilny kontrakt

Kod bazowy znajduje się w:

- `backend/l2_agents/strategy_engine.py` — kontrakt, kandydat, skan i rejestr;
- `backend/l2_agents/strategies/` — po jednym module na strategię;
- `backend/l2_agents/market_intelligence.py` — publikuje aktywny rejestr i
  pełny katalog wersji aktywnych pluginów w snapshotach;
- `backend/l2_agents/auction_adjudicator.py` — waliduje decyzję według pluginu;
- `backend/l2_agents/shadow_auction.py` — deleguje trigger do pluginu.

Każdy moduł w `l2_agents/strategies/` jest automatycznie odkrywany i musi
eksportować jedną zmienną `STRATEGY_PLUGIN`. Dodanie nowej strategii nie wymaga
edycji adjudykatora, snapshot buildera ani resolvera.

## Szablon nowej strategii

Utwórz plik `backend/l2_agents/strategies/h1_trend_pullback.py`:

```python
from l2_agents.strategy_engine import (
    StrategyCandidate, StrategyPlugin, StrategyScan, StrategySpec,
)


class H1TrendPullback(StrategyPlugin):
    spec = StrategySpec(
        strategy_id='H1_TREND_PULLBACK_V1',
        version='h1-trend-pullback-v1.0.0',
        display_name='H1 trend pullback',
        family='TREND_CONTINUATION',
        status='RESEARCH_ONLY',
        required_timeframes=('4h', '1h', '15m', '5m', '1m'),
        compatible_management_policies=(
            'P0_INITIAL_STOP', 'P1_STRUCTURAL', 'P2_HYBRID',
        ),
        long_zone_kinds=('FVG', 'RECENT_SUPPORT'),
        short_zone_kinds=('FVG', 'RECENT_RESISTANCE'),
        default_ttl_minutes=45,
        max_ttl_minutes=90,
        detector_mode='MECHANICAL',
        description='4h/1h aligned trend, 15m pullback, 5m confirmation.',
    )

    def scan(self, snapshot):
        # Tylko zamknięte świece i informacje dostępne w chwili decyzji.
        # Zwróć StrategyScan(candidates=(StrategyCandidate(...),)).
        return StrategyScan(diagnostics=('Detector not implemented yet.',))

    def triggered(self, plan, candle):
        touched = float(candle['low']) <= plan.zone_high
        return touched and (
            float(candle['close']) > plan.zone_high
            if plan.direction == 'LONG'
            else float(candle['close']) < plan.zone_low
        )


STRATEGY_PLUGIN = H1TrendPullback()
```

Po dodaniu modułu strategia jest zarejestrowana, ale nowe plany powstają tylko,
jeżeli jej ID znajduje się w `AUCTION_ENABLED_STRATEGIES`.

## Dodawanie, zmiana i wyłączanie

### Dodanie

1. Nowy moduł i nowe, nieużywane `strategy_id`.
2. Testy detektora bez look-ahead, stref, triggera i bramek ekonomii.
3. Replay na zamrożonym protokole.
4. Status `RESEARCH_ONLY`; dopiero po gate można utworzyć kolejną wersję ze
   statusem `SHADOW_ONLY`.
5. Dodać ID do `AUCTION_ENABLED_STRATEGIES`.

### Zmiana

Zmiana logiki sygnału, stopa, targetu, TTL, wymaganych danych albo parametrów
tworzy **nowe `strategy_id` i nową wersję**. Stary plugin pozostaje dostępny do
replay i interpretacji wcześniejszych wyników. Nie nadpisujemy historii.

### Wyłączenie

Usuń ID z `AUCTION_ENABLED_STRATEGIES`. To natychmiast blokuje nowe plany, ale
plugin pozostaje zainstalowany, dzięki czemu otwarte plany mogą się poprawnie
zamknąć, a historyczne wyniki są odtwarzalne.

Fizyczne usunięcie pliku jest ostatnim etapem i jest dozwolone dopiero, gdy nie
ma otwartych planów ani obowiązku replay tej wersji. Brak pluginu dla starego
planu działa fail-closed: resolver nie utworzy wejścia.

## Niezmienniki bezpieczeństwa

- Nieznane lub zduplikowane ID zatrzymuje konfigurację.
- Strategia spoza aktywnego snapshotu nie może zostać uzbrojona.
- Plugin nie może wyemitować kandydata pod cudzym ID.
- TTL nie może przekraczać limitu pluginu ani globalnych 240 minut.
- Kierunek musi pasować do kontraktu stref pluginu.
- Polityka zarządzania musi być jednocześnie obsługiwana przez resolver i
  zgodna z pluginem.
- Wyłączenie strategii nie zmienia wyników historycznych.
- Rejestr pluginów nie odblokowuje live tradingu.

## Obecne pluginy

| ID | Detektor | Status | Rola |
|---|---|---|---|
| `SAI1_FAILED_AUCTION` | mechaniczny M0 | shadow | odrzucona kontrola/replay |
| `SAI1_IFVG_FLIP` | AI-adjudicated | shadow | hipoteza IFVG |
| `SAI1_TREND_RETEST` | AI-adjudicated | shadow | dotychczasowa hipoteza trendu |

Następnym pluginem powinien być `H1_TREND_PULLBACK_V1`, ale jego detektor i
bramki ekonomii muszą zostać zaimplementowane i przetestowane jako nowa
hipoteza; nie wolno przemianować starego `SAI1_TREND_RETEST`.
