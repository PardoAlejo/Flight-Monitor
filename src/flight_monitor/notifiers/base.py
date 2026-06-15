"""Base protocol and utilities for notification plugins."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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
    # Flight timing
    total_duration: Optional[int] = None  # Total flight time in minutes
    departure_time: Optional[str] = None  # First segment departure time
    arrival_time: Optional[str] = None    # Last segment arrival time
    layovers: list[str] = field(default_factory=list)  # e.g. ["2h 30m en MIA"]
    # Price insights from Google Flights
    typical_price_low: Optional[float] = None   # Lower bound of typical range
    typical_price_high: Optional[float] = None  # Upper bound of typical range
    price_level: Optional[str] = None           # "low", "typical", or "high"

    @property
    def price_per_person(self) -> float:
        """Calculate price per person."""
        return self.price / self.adults if self.adults > 0 else self.price

    @property
    def duration_formatted(self) -> Optional[str]:
        """Format duration as 'Xh Ym'."""
        if self.total_duration is None:
            return None
        hours = self.total_duration // 60
        minutes = self.total_duration % 60
        if hours > 0 and minutes > 0:
            return f"{hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{minutes}m"


@dataclass
class DateAlternative:
    """A price found for an alternative departure date."""
    depart_date: str
    return_date: Optional[str]
    price: float
    currency: str
    is_cheapest: bool = False


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
    date_alternatives: list[DateAlternative] = field(default_factory=list)
    trend: Optional["TrendInfo"] = None

    @property
    def succeeded(self) -> bool:
        """Return whether the flight check produced a valid offer."""
        return self.offer is not None and self.error_message is None


@dataclass
class TrendInfo:
    """Price trend signals computed from historical data."""
    price_change: Optional[float] = None       # vs previous check (negative = cheaper)
    price_change_pct: Optional[float] = None   # percentage change vs previous
    is_all_time_low: bool = False               # lowest price ever seen for this route
    vs_avg_pct: Optional[float] = None         # % below/above hist. avg (negative = cheaper)
    historical_min: Optional[float] = None     # all-time lowest price
    historical_avg: Optional[float] = None     # historical average price
    record_count: int = 0                      # how many data points we have


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
