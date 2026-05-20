"""Entry point for running flight_monitor as a module."""

import argparse
from datetime import datetime

from .clients.serpapi import SerpApiClient
from .config import load_config
from .monitor import FlightMonitor
from .notifiers.email import EmailNotifier
from .notifiers.telegram import TelegramNotifier
from .scheduler import RetryScheduler
from .storage.sqlite import SQLiteStorage


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Monitor flight prices and get notified on price drops"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single check and exit (useful for cron jobs)",
    )
    parser.add_argument(
        "--scheduled",
        action="store_true",
        help="Run only when a scheduled slot or retry window is due",
    )
    args = parser.parse_args()

    # Load configuration
    config = load_config()

    # Validate configuration
    if not config.serpapi_key:
        print("[Error] Falta la API key de SerpApi. Configura SERPAPI_KEY en .env")
        return

    if not config.flights:
        print("[Error] No hay vuelos configurados. Usa flights.yaml o variables de entorno.")
        return

    # Initialize components
    client = SerpApiClient(config.serpapi_key)
    storage = SQLiteStorage(config.db_path)

    # Initialize notifiers
    notifiers = [
        EmailNotifier(
            sender=config.email_sender,
            password=config.email_password,
            receiver=config.email_receiver,
        ),
        TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        ),
    ]

    # Create monitor
    monitor = FlightMonitor(config, client, storage, notifiers)

    if args.scheduled:
        scheduler = RetryScheduler(
            state_path=config.scheduler_state_path,
            scheduled_times=config.scheduled_times,
            retry_delay_minutes=config.retry_delay_minutes,
        )
        now = datetime.now()
        slot = scheduler.next_due_slot(now)
        if slot is None:
            print("[Scheduler] No hay ejecucion pendiente en este momento.")
            return

        print(
            "[Scheduler] Ejecutando ventana "
            f"{slot.scheduled_for.strftime('%Y-%m-%d %H:%M')}."
        )
        success = monitor.run_once()
        scheduler.mark_attempt(slot, datetime.now(), succeeded=success)
        if not success:
            raise SystemExit(1)
    elif args.once:
        # Single check mode (for cron)
        if not monitor.run_once():
            raise SystemExit(1)
    else:
        # Continuous mode (loop)
        monitor.run()


if __name__ == "__main__":
    main()
