# Portfolio dwóch książek — $500 kapitału, cel $5/dzień

**Status:** Book A zamrożona (research). Book B — faza kreatywna / S79+.

## Intencja

| Księga | Kapitał | Rola | Oczekiwany profil |
|--------|--------:|------|-------------------|
| **A — S73+BTC** | $250 | „Rentownik” — trend long na altach w hossie | Niski turnover, dodatni OOS holdout, duże luki w bear |
| **B — TBD (S79)** | $250 | „Silnik luki” — zarabia gdy A śpi + szuka asymetrii | Wyższa wariancja, krótszy horyzont, inne dane / reżim |

Cel produktowy: **$5/dzień średnio** na całym portfelu ($500).  
Cel researchu Book B: **maksymalizować $/dzień przy akceptowalnym DD**, nie kopiować Book A.

## Matematyka celu (bez złudzeń, z kierunkiem)

| Składnik | $/dzień (holdout, est.) | Udział w $5 |
|----------|------------------------:|------------:|
| Book A (S73+BTC @ $250) | ~0,27 | ~5% |
| **Brakuje** | **~4,73** | **95%** |

Druga książka **nie musi** dawać $4,73 każdego dnia — może to być **mieszanka**:

1. Stały dodatek (np. carry / cash yield) — centy.
2. **Reżimowy** dodatek gdy BTC &lt; SMA200 (A wyłączone) — dolary w tygodniach, zero w hossie.
3. **Rzadkie duże dni** (makro, kaskady likwidacji, listingi) — średnia rośnie bez codziennego 2%.

Żeby **średnia** dojść do $5, Book B musi w praktyce dostarczyć **~19× więcej dolarów dziennie niż Book A** na tym samym kapitale — albo portfel musi użyć **wyższej ekspozycji / leverage** tam, gdzie edge jest lokalny (tylko w zdefiniowanych oknach).

## Zasady współistnienia

1. **Osobne subkonta lub tagi** — nigdy nie mieszać marginu Book B z tygodniowym rebalance A.
2. **Brak korelacji sygnału** — B nie robi „tego samego TSMOM na innych coinach”.
3. **Kalendarz:** A = rebalance cotygodniowy; B może być intraday / event / settlement.
4. **Raport:** zawsze **$/dzień per book** + **suma** + **gap do $5**.

## Dokumenty

- [BOOK_A_S73_BTC_FROZEN.md](./BOOK_A_S73_BTC_FROZEN.md) — zamrożony protokół.
- [BOOK_A_RISK_OVERLAY_FROZEN.md](./BOOK_A_RISK_OVERLAY_FROZEN.md) — RM_composite_v1 (breadth/vol/DD).
- [BOOK_B_S79_CREATIVE_BRIEF.md](./BOOK_B_S79_CREATIVE_BRIEF.md) — kandydaci i plan badawczy.
- [BOOK_B_RISK_SHARED.md](./BOOK_B_RISK_SHARED.md) — S82 macro + wskaźniki A.

## Następny krok implementacyjny (po wyborze kandydata B)

1. Przenieść kod S73 ze scratchpada do `backend/backtest/` + `protocol.json`.
2. Uruchomić **S79** jako osobny runner z tym samym split dev / val / holdout co S70 panel.
3. Paper: dwa wirtualne portfele w `paper_engine` lub dwa procesy.
