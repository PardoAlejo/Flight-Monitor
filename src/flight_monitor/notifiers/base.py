"""Base protocol and utilities for notification plugins."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class FlightOffer:
    """Represents a flight offer."""
    price: float
    currency: str
    airline: str
    segments: list[str]
    stops: int
    origin: str
    destination: str
    depart_date: str
    return_date: Optional[str] = None
    adults: int = 1  # Number of passengers (for per-person price calculation)
    price_category: str = "other"  # "best" (LOW) or "other"
    # Price insights from Google Flights
    typical_price_low: Optional[float] = None   # Lower bound of typical range
    typical_price_high: Optional[float] = None  # Upper bound of typical range
    price_level: Optional[str] = None           # "low", "typical", or "high"

    @property
    def price_per_person(self) -> float:
        """Calculate price per person."""
        return self.price / self.adults if self.adults > 0 else self.price


@dataclass
class PriceRecord:
    """Represents a historical price record."""
    price: float
    currency: str
    airline: str
    checked_at: str
    price_category: str = "other"


@dataclass
class FlightCheckResult:
    """Result of a flight price check."""
    origin: str
    destination: str
    depart_date: str
    return_date: Optional[str] = None
    offer: Optional[FlightOffer] = None
    discount_pct: float = 0.0  # Percentage below typical_price_low
    recommended: bool = False  # True if price is below typical_price_low
    error_message: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        """Return whether the flight check produced a valid offer."""
        return self.offer is not None and self.error_message is None


class Notifier(ABC):
    """Abstract base class for notification plugins."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if this notifier has all required configuration."""
        pass

    @abstractmethod
    def send_summary(self, results: list["FlightCheckResult"]) -> bool:
        """
        Send a daily summary of all flight checks.

        Args:
            results: List of flight check results

        Returns:
            True if summary was sent successfully, False otherwise
        """
        pass
