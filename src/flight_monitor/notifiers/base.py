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


class Notifier(ABC):
    """Abstract base class for notification plugins."""

    @abstractmethod
    def send(
        self,
        offer: FlightOffer,
        stats: PriceStats,
        discount_pct: float,
    ) -> bool:
        """
        Send a notification about a flight offer.

        Args:
            offer: The current flight offer details
            stats: Historical price statistics
            discount_pct: Percentage below average LOW price

        Returns:
            True if notification was sent successfully, False otherwise
        """
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if this notifier has all required configuration."""
        pass

    def build_message(
        self,
        offer: FlightOffer,
        stats: PriceStats,
        discount_pct: float,
    ) -> str:
        """Build a standard notification message."""
        route = f"{offer.origin} -> {offer.destination}"
        ret = f" / Regreso: {offer.return_date}" if offer.return_date else ""

        lines = [
            "ALERTA DE VUELO BARATO",
            "",
            f"Ruta:    {route}",
            f"Fecha:   {offer.depart_date}{ret}",
            "",
            f"Precio actual:     {offer.currency} {offer.price:,.0f}",
        ]

        if stats.avg_low_price:
            lines.append(f"Promedio LOW:      {offer.currency} {stats.avg_low_price:,.0f}")
            lines.append(f"")
            lines.append(f"*** {discount_pct:.1f}% POR DEBAJO DEL PROMEDIO ***")

        lines.extend([
            "",
            f"Aerolinea: {offer.airline}",
            f"Escalas:   {offer.stops}",
            "Itinerario:",
        ])

        for seg in offer.segments:
            lines.append(f"  - {seg}")

        lines.extend([
            "",
            "Busca en: https://www.google.com/flights",
        ])

        return "\n".join(lines)
