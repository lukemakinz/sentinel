# Raspberry Pi + Telegram — runbook

Sentinel na Pi zbiera dane, prowadzi shadow (mechaniczny baseline + AI z limitem
$/dzień), skanuje altcoiny (setup search), rozlicza dziennik i raportuje na
Telegram. **Nie składa zleceń.** Handlu na żywo nie da się włączyć z telefonu.

## Co działa na Pi

| Usługa | Rola |
|---|---|
| `ingester` | WebSockety Binance, OI co 5 min, shadow co 5 min, setup search co 15 min, próg wieloryba co 1 h, czyszczenie 02:00 UTC |
| `telegram_bot` | komendy z telefonu, watchdog feedu (osobny proces), podsumowanie dnia 07:00 UTC |
| `backend`, `frontend`, `nginx` | dashboard (przez Tailscale) |
| `redis` | cache |
| `celery_*` | **wyłączone** (profil `celery`); Beat uruchamiałby stary pipeline L1→L2, którego agenci wołają AI poza limitem budżetu |

## 1. Bot Telegram (5 min, na telefonie)

1. W Telegramie otwórz `@BotFather` → `/newbot` → nazwa → skopiuj **token**.
2. Na Pi w `.env`: `TELEGRAM_BOT_TOKEN=<token>`, `TELEGRAM_CHAT_ID=` (puste).
3. Uruchom bota (krok 3), wyślij mu `/start`. Odpowie: `Twoje chat_id: 123…`.
4. Wpisz `TELEGRAM_CHAT_ID=123…` do `.env`, zrestartuj: `docker compose -f docker-compose.pi.yml restart telegram_bot`.

Bot wykonuje komendy wyłącznie z tego `chat_id`; inne czaty są ignorowane.
Tokena nie wklejaj w rozmowie ani do repo (`.env` jest w `.gitignore`).

## 2. Sprzęt i system

- **SSD/NVMe zamiast karty SD** — baza zapisuje dziesiątki tysięcy wierszy dziennie.
- Raspberry Pi OS 64-bit (aarch64). Docker: `curl -fsSL https://get.docker.com | sh`.
- **Tailscale** (darmowy plan osobisty) na Pi i telefonie: `curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`.
  Dashboard: `http://<nazwa-pi>` w sieci Tailscale; bez otwierania portów w routerze.

## 3. Wdrożenie

```bash
git clone <repo> sentinel && cd sentinel
cp .env.example .env      # uzupełnij: DJANGO_SECRET_KEY, OPENAI_API_KEY, TELEGRAM_*
./deploy-pi.sh            # buduje obrazy (TA-Lib jako gotowe koło aarch64) i startuje
docker compose -f docker-compose.pi.yml logs -f ingester telegram_bot
```

Przy pierwszym starcie baza jest pusta: ingester sam dociąga świece; order book,
CVD i OI potrzebują kilku minut, zanim jakość danych pozwoli na analizy.

## 4. Komendy w telefonie

| Komenda | Co robi |
|---|---|
| `/status` | wiek danych, pauza, wydatek AI dziś, otwarte setupy |
| `/scan [SYMBOL]` | setup search teraz (ok. 15–20 s) |
| `/raport` | dziennik setupów (ścisłe RR≥1:3 i wszystkie) + shadow AI vs baseline |
| `/koszt` | AI dziś i w 7 dni |
| `/pauza`, `/wznow` | wstrzymuje / wznawia shadow, AI i dziennik (feed zbiera dalej) |

Alerty automatyczne: nowy `WAIT_RETEST` i `WAIT_MSS` (zmienna
`TELEGRAM_ALERT_STATUSES`), wynik zaalertowanego setupu, feed nieaktualny > 5 min
i powrót feedu.

## 5. Kopie zapasowe

Baza: wolumen `db_data` (`/app/db/db.sqlite3`). Nocny backup, np. w crontab na Pi:

```bash
30 3 * * * docker compose -f ~/sentinel/docker-compose.pi.yml exec -T backend python -c \
  "import sqlite3; sqlite3.connect('/app/db/db.sqlite3').backup(sqlite3.connect('/app/db/backup.sqlite3'))"
```

## 6. Koszty

| Pozycja | Miesięcznie |
|---|---:|
| Prąd Pi (5–8 W) | ok. 3–5 zł |
| Tailscale, Telegram, dane Binance | 0 zł |
| AI shadow (twardy limit `AUCTION_AI_DAILY_BUDGET_USD`, domyślnie $1/dzień) | do ~$30, realnie mniej |

Koszt każdej analizy AI jest zapisywany; `/koszt` i raport pokazują sumy.
