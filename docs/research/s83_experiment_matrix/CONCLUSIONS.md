# Wnioski z eksperymentów S83

## Co działało (validation paź 2025 – sty 2026)

| Hipoteza | $/dzień val | Uwaga |
|----------|------------:|-------|
| **A + RM, bez BTC w koszyku** | **+$0,31** | Największy skok; BTC jako filtr SMA200 zostaje, ale **nie jako pozycja** |
| **B S83 quiet Donchian** | **+$0,10** | Tylko **8 tradów** — mała próba |
| **A_noBTC + B_S83** | **+$0,42** | Gap do $5: **~$4,59/d** (najlepszy dotąd replay) |

## Co nie działało / ostrzeżenia

- **S83 na development:** **−$0,39/d** (68 tradów) — edge **nie jest stabilny** między oknami; val może być szum.
- **Macro (S80/S82):** ujemne lub ~0 po filtrach.
- **Complement-only B:** 0 tradów (A zbyt często pełna ekspozycja).
- **Dodanie BTC do portfela momentum** pogarszało validation vs **same alty**.

## Wskaźniki (z Book A risk research)

- Wysoka **vol BTC** → słabsze fwd; **breadth** → lepsze fwd.
- S83 = handel breakout 1h tylko gdy vol niska + breadth OK — zgodne z wskaźnikami.

## Decyzje operacyjne (propozycja freeze)

1. **Book A:** `include_btc_in_universe=False` + `BOOK_A_RISK_DEFAULT` (nazwa: **BOOK_A_ALT_RM**).
2. **Book B:** **S83** jako eksperymentalna noga; paper z **małym risk ($6)** i hard cap tradów/miesiąc.
3. **Cel $5/d:** przy **+$0,42/d** na $500 potrzeba ~**12×** kapitału (~$6k) **lub** lepszy B — nie kolejny grid na tym samym 92-dniowym val.

## S83 v2 + walk-forward (`book_ab_walkforward/`)

- **v2** (vol≤45%, breadth≥50%, max 2 tradów/tydz.): tłumi straty B w WF1; **AB v2 ~$1,46/d** na WF1–2 (bull).
- **WF3 (lis–sty):** Book A **$0** — cały zysk A w validation to **październik** (+$28); lis–sty flat.
- Na pełnym validation **v1 B** nadal lepszy (+$0,10/d) niż v2 (~$0).

## S84 router (`s84_quiet_router/`)

| Okno | A $/d | AB v1 | AB v2 | AB router |
|------|------:|------:|------:|----------:|
| **full 2025** | +0,66 | +0,49 | **+0,60** | +0,49 |
| validation | +0,31 | **+0,41** | +0,31 | **+0,41** |

Router = v1 w chop (validation), v2 w bull — **validation jak v1**, cały 2025 najlepszy **AB v2** (gap **~$4,40/d**).

## Następne kroki

- **Paper 8 tyg.** — `run_book_ab_paper_snapshot` + [BOOK_AB_PAPER_PROTOCOL.md](../../strategies/BOOK_AB_PAPER_PROTOCOL.md)
- Pobrać **świeże dane** po 2026-01-01 zanim snapshot będzie „live”.
