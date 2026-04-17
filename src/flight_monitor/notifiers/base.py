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
    price_category: str = "other"  # "best" (LOW) or "other"
    # Price insights from Google Flights
    typical_price_low: Optional[float] = None   # Lower bound of typical range
    typical_price_high: Optional[float] = None  # Upper bound of typical range
    price_level: Optional[str] = None           # "low", "typical", or "high"


@dataclass
class PriceRecord:
    """Represents a historical price record."""
    price: float
    currency: str
    airline: str
    checked_at: str
    price_category: str = "other"


@dataclass
class PriceStats:
    """Statistics for price history."""
    avg_low_price: Optional[float]  # Average of "best" category prices
    min_price: Optional[float]
    count_low: int  # Number of "best" category records


@dataclass
class FlightCheckResult:
    """Result of a flight price check."""
    offer: FlightOffer
    discount_pct: float  # Percentage below typical_price_low
    recommended: bool    # True if price is below typical_price_low


class Notifier(ABC):
    """Abstract base class for notification plugins."""

    @abstractmethod
    def send(
        self,
        offer: FlightOffer,
        discount_pct: float,
    ) -> bool:
        """
        Send a notification about a flight offer.

        Args:
            offer: The current flight offer details
            discount_pct: Percentage below typical price range

        Returns:
            True if notification was sent successfully, False otherwise
        """
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if this notifier has all required configuration."""
        pass

    def send_summary(self, results: list["FlightCheckResult"]) -> bool:
        """
        Send a daily summary of all flight checks.

        Args:
            results: List of flight check results

        Returns:
            True if summary was sent successfully, False otherwise
        """
        return False  # Default: do nothing, subclasses can override
