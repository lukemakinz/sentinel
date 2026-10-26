# UX/UI Audit — 2026-04-29

## Cel

System ma być prosty, intuicyjny i operacyjny.

Obecnie największa wartość dla użytkownika jest w:
- sygnałach,
- pozycjach,
- kontroli ryzyka,
- live exchange ops,
- backteście.

## Co zostawić jako rdzeń

To powinno być zawsze łatwo dostępne:
- `Command Center`
- `Monitor`
- `Risk Controls`
- `Backtest Lab`
- `Exchange Ops` na dashboardzie

To są elementy, które bezpośrednio pomagają podjąć decyzję i zarządzać pozycją.

## Co traktować jako warstwę eksperymentalną

Na dziś:
- `AI Agents`
- część narracyjnych paneli analitycznych
- rozbudowane opisy, które nie pomagają w wykonaniu akcji

Rekomendacja:
- nie usuwać tego z repo,
- schować za sekcją `Experimental`,
- nie budować głównego workflow wokół tej warstwy.

## Najważniejsze problemy UX

### 1. Dashboard był zbyt szeroki poznawczo

Użytkownik widział naraz:
- sygnały,
- status L1,
- AI agents,
- pozycje,
- watchlistę,
- dodatkowe meta-warstwy.

To zwiększało chaos. Lepszy kierunek:
- najpierw sygnał,
- potem pozycja / risk,
- potem exchange,
- na końcu eksperymentalne panele.

### 2. AI wyglądało jak core systemu, mimo że nie jest dziś krytyczne

To mogło wprowadzać użytkownika w błąd.

Lepszy model:
- AI jako opcjonalny insight,
- nie jako pierwszy ekran decyzyjny.

### 3. Brak jednego jasnego modelu “co robić teraz”

Dobry dashboard powinien odpowiadać na 3 pytania:
- czy mam sygnał,
- czy mam pozycję,
- czy exchange/live działa poprawnie.

## Co już zostało poprawione

- login jest spójny wizualnie z aplikacją,
- exchange ops są dostępne z dashboardu,
- wykres exchange ma overlaye:
  - fills
  - trades
  - open orders
  - positions
  - done/canceled orders
- AI agents są schowane jako `Experimental Layer`

## Co poprawić dalej

### Krótki termin

1. Dodać prosty pasek `Next Action` na dashboardzie.
   Przykład:
   - `No signal`
   - `1 signal waiting`
   - `2 open positions`
   - `Live sync stale`

2. Dodać legendę / tooltip dla markerów na wykresie exchange.

3. Dodać mały status świeżości:
   - last sync
   - last fills sync
   - last orders sync

### Średni termin

1. Rozważyć wydzielenie `Exchange Ops` do osobnej strony, jeśli dashboard zacznie znowu puchnąć.

2. Uprościć `How it works`, bo dziś jest bardzo gęste.
   Lepsze byłyby:
   - `Quick Start`
   - `Advanced / Experimental`

3. Jeśli `S6 spot` ruszy, pokazać ją jako osobny, spokojniejszy tryb użytkowania, a nie mieszać z futures.

## Wniosek

Najbardziej sensowna architektura produktu na dziś:
- `S1C` i live futures jako główny silnik,
- exchange monitoring jako narzędzie operacyjne,
- AI jako warstwa opcjonalna,
- `S6 spot` jako przyszły drugi, prostszy tor.
