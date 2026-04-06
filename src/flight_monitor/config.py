"""Configuration management using environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv


@dataclass
class FlightConfig:
    """Configuration for a single flight to monitor."""
    origin: str
    destination: str
    depart_date: str
    return_date: Optional[str] = None
    adults: int = 1
    currency: str = "USD"
    alert_threshold_pct: float = 0.0


@dataclass
class AppConfig:
    """Application-wide configuration."""
    # SerpApi
    serpapi_key: str

    # Email notifications
    email_sender: Optional[str] = None
    email_password: Optional[str] = None
    email_receiver: Optional[str] = None

    # Telegram notifications
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    # Database
    db_path: str = "flight_prices.db"

    # Monitoring
    check_interval_minutes: int = 60

    # Flights to monitor
    flights: list[FlightConfig] = field(default_factory=list)


def load_flights_from_yaml(path: Path) -> list[FlightConfig]:
    """Load flight configurations from a YAML file."""
    if not path.exists():
        return []

    with open(path, "r") as f:
        data = yaml.safe_load(f)

    if not data or "flights" not in data:
        return []

    flights = []
    for flight_data in data["flights"]:
        flights.append(FlightConfig(
            origin=flight_data["origin"],
            destination=flight_data["destination"],
            depart_date=flight_data["depart_date"],
            return_date=flight_data.get("return_date"),
            adults=flight_data.get("adults", 1),
            currency=flight_data.get("currency", "USD"),
            alert_threshold_pct=flight_data.get("alert_threshold_pct", 0.0),
        ))

    return flights


def load_config(env_path: Optional[Path] = None, flights_path: Optional[Path] = None) -> AppConfig:
    """
    Load configuration from environment variables and optional YAML file.

    Args:
        env_path: Path to .env file (default: looks in current directory)
        flights_path: Path to flights.yaml file (default: looks in current directory)

    Returns:
        AppConfig with all settings loaded
    """
    # Load .env file
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    # Load flights from YAML
    flights_file = flights_path or Path("flights.yaml")
    flights = load_flights_from_yaml(flights_file)

    # If no flights.yaml, check for single flight in env vars (backwards compatibility)
    if not flights:
        origin = os.getenv("FLIGHT_ORIGIN")
        destination = os.getenv("FLIGHT_DESTINATION")
        depart_date = os.getenv("FLIGHT_DEPART_DATE")

        if origin and destination and depart_date:
            flights.append(FlightConfig(
                origin=origin,
                destination=destination,
                depart_date=depart_date,
                return_date=os.getenv("FLIGHT_RETURN_DATE"),
                adults=int(os.getenv("FLIGHT_ADULTS", "1")),
                currency=os.getenv("FLIGHT_CURRENCY", "USD"),
                alert_threshold_pct=float(os.getenv("ALERT_THRESHOLD_PCT", "0.0")),
            ))

    return AppConfig(
        serpapi_key=os.getenv("SERPAPI_KEY", ""),
        email_sender=os.getenv("EMAIL_SENDER"),
        email_password=os.getenv("EMAIL_PASSWORD"),
        email_receiver=os.getenv("EMAIL_RECEIVER"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        db_path=os.getenv("DB_PATH", "flight_prices.db"),
        check_interval_minutes=int(os.getenv("CHECK_INTERVAL_MINUTES", "60")),
        flights=flights,
    )
