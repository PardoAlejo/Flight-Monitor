"""Entry point for running flight_monitor as a module."""

import argparse

from .clients.serpapi import SerpApiClient
from .config import load_config
from .monitor import FlightMonitor
from .notifiers.email import EmailNotifier
from .notifiers.telegram import TelegramNotifier
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

    if args.once:
        # Single check mode (for cron)
        monitor.run_once()
    else:
        # Continuous mode (loop)
        monitor.run()


if __name__ == "__main__":
    main()
