# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Flight Monitor tracks flight prices using Google Flights (via SerpApi) and sends notifications (email/Telegram) when prices reach historical minimums. Supports monitoring multiple flights concurrently.

## Commands (UV)

```bash
# Sync dependencies (creates venv automatically)
uv sync

# Run the monitor (continuous mode)
uv run python -m flight_monitor

# Run single check and exit (for cron)
uv run python -m flight_monitor --once

# Run linter
uv run ruff check src/

# Run type checker
uv run mypy src/
```

## Scheduled Execution (Cron)

To save API calls, run checks at specific times instead of continuously:

```bash
# Edit crontab
crontab -e

# Add these lines for 6 AM and 6 PM daily:
0 6 * * * cd /path/to/Flight-Monitor && uv run python -m flight_monitor --once >> monitor.log 2>&1
0 18 * * * cd /path/to/Flight-Monitor && uv run python -m flight_monitor --once >> monitor.log 2>&1
```

**API usage with 2 flights:**
- 2 checks/day × 2 flights = 4 API calls/day
- ~120 calls/month (within 100-call free tier if monitoring 1 flight)

## Architecture

```
src/flight_monitor/
├── __main__.py          ← Entry point, dependency injection setup
├── config.py            ← Configuration from .env + flights.yaml
├── monitor.py           ← FlightMonitor orchestrator (async)
├── clients/
│   └── serpapi.py       ← SerpApiClient (Google Flights)
├── storage/
│   └── sqlite.py        ← SQLiteStorage with DI
└── notifiers/
    ├── base.py          ← Notifier protocol + data classes
    ├── email.py         ← EmailNotifier plugin
    └── telegram.py      ← TelegramNotifier plugin
```

**Key design patterns:**
- **Dependency Injection**: All components receive dependencies via constructor
- **Plugin Architecture**: Notifiers implement `Notifier` protocol
- **Async Concurrency**: Multiple flights checked in parallel
- **FlightClient Protocol**: Easy to swap SerpApi for another provider

**Data flow:**
1. `__main__.py` loads config and injects dependencies into `FlightMonitor`
2. `FlightMonitor.check_all_flights_async()` spawns concurrent checks
3. `SerpApiClient.fetch_cheapest_offer()` queries Google Flights, returns `FlightOffer`
4. `SQLiteStorage` handles persistence, returns `PriceRecord`
5. Configured `Notifier` plugins receive `FlightOffer` + `PriceRecord`

## Configuration

**Environment variables** (`.env`):
- `SERPAPI_KEY` - SerpApi key (https://serpapi.com)
- `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVER` - Gmail SMTP
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` - Telegram bot

**Multiple flights** (`flights.yaml`):
```yaml
flights:
  - origin: BOG
    destination: MAD
    depart_date: "2025-12-01"
```

## Adding a New Notifier

1. Create `src/flight_monitor/notifiers/slack.py`
2. Implement `Notifier` protocol from `base.py`
3. Add to `__main__.py` notifiers list

## Adding a New Flight Provider

1. Create `src/flight_monitor/clients/newprovider.py`
2. Implement `fetch_cheapest_offer(flight: FlightConfig) -> Optional[FlightOffer]`
3. Swap client in `__main__.py`

## Database

SQLite table `prices`: `id`, `origin`, `destination`, `depart_date`, `return_date`, `price`, `currency`, `airline`, `checked_at`
