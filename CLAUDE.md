# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Flight Monitor tracks flight prices using Google Flights (via SerpApi) and sends a **daily summary** (email/Telegram) with purchase recommendations based on Google's typical price range. Supports monitoring multiple flights concurrently.

## Commands (UV)

```bash
# Sync dependencies (creates venv automatically)
uv sync

# Run the monitor (continuous mode)
uv run python -m flight_monitor

# Run single check and exit (for cron)
uv run python -m flight_monitor --once

# Run only when a scheduled slot or retry window is due
uv run python -m flight_monitor --scheduled

# Run linter
uv run ruff check src/

# Run type checker
uv run mypy src/
```

## Scheduled Execution

The recommended production setup uses `--scheduled` with an hourly cron/launchd job. The scheduler reads a JSON state file and only runs when a configured time slot is due or a previous run failed:

```bash
# cron: run every hour, execute only at 10:00, 15:30 or their retries
0 * * * * cd /path/to/Flight-Monitor && uv run python -m flight_monitor --scheduled >> monitor.log 2>&1
```

**macOS launchd**: use `launchd/com.flight-monitor.plist.example` as a template for an hourly LaunchAgent.

**API usage with 2 flights and 2 slots/day:**
- 2 checks/day × 2 flights = 4 API calls/day (~120/month)
- SerpApi free tier: 100 calls/month → limit to 1 flight or 1 slot/day

## GitHub Actions

The workflow `.github/workflows/monitor.yml` runs automatically at 11:00 AM and 4:00 PM Colombia time (16:00 and 21:00 UTC) daily.

**Required secrets** (Settings → Secrets and variables → Actions):
- `SERPAPI_KEY` — SerpApi API key
- `FLIGHTS_YAML` — Contents of your `flights.yaml` file
- `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVER` — Gmail credentials (optional)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — Telegram credentials (optional)

**Manual trigger**: Actions → Flight Monitor → Run workflow

## Architecture

```
src/flight_monitor/
├── __main__.py          ← Entry point, arg parsing, dependency injection
├── config.py            ← Configuration from .env + flights.yaml
├── monitor.py           ← FlightMonitor orchestrator (async)
├── scheduler.py         ← RetryScheduler — persists slot state in JSON
├── clients/
│   └── serpapi.py       ← SerpApiClient (Google Flights + price_insights)
├── storage/
│   └── sqlite.py        ← SQLiteStorage with DI
└── notifiers/
    ├── base.py          ← Notifier protocol, FlightOffer (with duration), FlightCheckResult
    ├── email.py         ← EmailNotifier — rich daily summary via Gmail SMTP
    └── telegram.py      ← TelegramNotifier — compact summary via Bot API
```

**Key design patterns:**
- **Dependency Injection**: All components receive dependencies via constructor
- **Plugin Architecture**: Notifiers implement `Notifier` abstract class (`is_configured()`, `send_summary()`)
- **Async Concurrency**: Multiple flights checked in parallel via `ThreadPoolExecutor` + `asyncio.gather`
- **FlightClient Protocol**: Easy to swap SerpApi for another provider

**Data flow:**
1. `__main__.py` loads config and injects dependencies into `FlightMonitor`
2. `FlightMonitor.check_all_flights_async()` spawns concurrent checks
3. `SerpApiClient.fetch_cheapest_offer()` queries Google Flights, returns `FlightOffer` with `typical_price_low`, `typical_price_high`, `price_level`, `total_duration`
4. `SQLiteStorage.insert_price()` persists the record
5. `FlightMonitor.should_recommend()` compares `offer.price` vs `offer.typical_price_low` — recommends if price is below the typical range lower bound
6. `FlightMonitor._send_summary()` calls `notifier.send_summary(results)` on all configured notifiers

## Notification Features

Both Email and Telegram notifiers include:
- **Spanish date formatting**: "Lun 25 May 2026" with day of week
- **Trip duration**: Days between departure and return
- **Flight duration**: Total flight time (e.g., "12h 30m")
- **Visual price indicators**: 🟢 (low/buy), 🟡 (typical), 🔴 (high)
- **Quick summary table**: Overview of all flights at the top (email only)
- **Google Flights links**: Direct search URLs (email only)

## Alert Logic

Recommendation is triggered when `price < typical_price_low` (discount_pct > 0):

```python
discount_pct = (typical_price_low - price) / typical_price_low * 100
recommended = discount_pct > 0
```

If Google doesn't return `price_insights` for a route, no recommendation is made.

## Configuration

**Environment variables** (`.env`):
- `SERPAPI_KEY` — SerpApi key (required)
- `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVER` — Gmail SMTP (optional; multiple receivers comma-separated)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — Telegram bot (optional)
- `DB_PATH` — SQLite database path (default: `flight_prices.db`)
- `CHECK_INTERVAL_MINUTES` — interval for continuous mode (default: 60)
- `SCHEDULED_TIMES` — comma-separated HH:MM slots for `--scheduled` (default: `10:00,15:30`)
- `RETRY_DELAY_MINUTES` — wait before retrying a failed slot (default: 60)
- `SCHEDULER_STATE_PATH` — JSON state file for scheduler (default: `.flight_monitor_scheduler.json`)

**Flights** (`flights.yaml`):
```yaml
flights:
  - origin: BOG
    destination: MAD
    depart_date: "2026-12-01"
    return_date: "2026-12-15"  # optional
    adults: 1                  # optional, default 1
    currency: USD              # optional, default USD
```

Backwards-compatible: single flight can also be set via `FLIGHT_ORIGIN`, `FLIGHT_DESTINATION`, `FLIGHT_DEPART_DATE` env vars.

## Adding a New Notifier

1. Create `src/flight_monitor/notifiers/slack.py`
2. Subclass `Notifier` from `base.py` and implement `is_configured()` and `send_summary(results)`
3. Add to `__main__.py` notifiers list

## Adding a New Flight Provider

1. Create `src/flight_monitor/clients/newprovider.py`
2. Implement `fetch_cheapest_offer(flight: FlightConfig) -> Optional[FlightOffer]`
3. Swap client in `__main__.py`

## Database

SQLite table `prices`:

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | autoincrement |
| `origin` | TEXT | IATA code |
| `destination` | TEXT | IATA code |
| `depart_date` | TEXT | YYYY-MM-DD |
| `return_date` | TEXT | nullable |
| `price` | REAL | total price (all passengers) |
| `currency` | TEXT | ISO currency code |
| `airline` | TEXT | first leg airline |
| `price_category` | TEXT | `"best"` (LOW) or `"other"` |
| `checked_at` | TEXT | ISO 8601 UTC timestamp |

`price_category` column is migrated automatically if the DB was created before it was added.
