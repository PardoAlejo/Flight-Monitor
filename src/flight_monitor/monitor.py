"""Flight price monitor with support for multiple flights."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, Protocol

from .config import AppConfig, FlightConfig
from .notifiers.base import FlightOffer, Notifier, PriceStats
from .storage.sqlite import SQLiteStorage

# Minimum discount percentage to trigger alert (10% below average LOW)
ALERT_DISCOUNT_THRESHOLD = 10.0


class FlightClient(Protocol):
    """Protocol for flight API clients."""

    def fetch_cheapest_offer(self, flight: FlightConfig) -> Optional[FlightOffer]:
        """Fetch the cheapest flight offer for the given configuration."""
        ...


class FlightMonitor:
    """Monitor flight prices and send notifications on price drops."""

    def __init__(
        self,
        config: AppConfig,
        client: FlightClient,
        storage: SQLiteStorage,
        notifiers: list[Notifier],
    ):
        """
        Initialize the flight monitor.

        Args:
            config: Application configuration
            client: Flight API client (SerpApi, Amadeus, etc.)
            storage: Price history storage
            notifiers: List of notification plugins
        """
        self.config = config
        self.client = client
        self.storage = storage
        self.notifiers = [n for n in notifiers if n.is_configured()]

    def calculate_discount(self, current_price: float, avg_low_price: float) -> float:
        """
        Calculate the percentage discount from average LOW price.

        Args:
            current_price: Current flight price
            avg_low_price: Historical average of LOW category prices

        Returns:
            Discount percentage (positive means cheaper than average)
        """
        if avg_low_price <= 0:
            return 0.0
        return ((avg_low_price - current_price) / avg_low_price) * 100

    def should_alert(self, current_price: float, stats: PriceStats) -> tuple[bool, float]:
        """
        Determine if a notification should be sent.

        Alert only if price is 10% or more below the average LOW price.

        Args:
            current_price: Current flight price
            stats: Historical price statistics

        Returns:
            Tuple of (should_alert, discount_percentage)
        """
        # Need at least some LOW price history to compare
        if stats.avg_low_price is None or stats.count_low < 1:
            return False, 0.0

        discount_pct = self.calculate_discount(current_price, stats.avg_low_price)

        # Alert if 10% or more below average LOW price
        should_notify = discount_pct >= ALERT_DISCOUNT_THRESHOLD

        return should_notify, discount_pct

    def _notify_all(self, offer: FlightOffer, stats: PriceStats, discount_pct: float) -> None:
        """Send notifications through all configured notifiers."""
        for notifier in self.notifiers:
            notifier.send(offer, stats, discount_pct)

    def check_flight(self, flight: FlightConfig) -> None:
        """
        Check price for a single flight.

        Args:
            flight: Flight configuration to check
        """
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        route = f"{flight.origin} -> {flight.destination}"
        print(f"\n{'='*50}")
        print(f"[{now}] Chequeando {route} ({flight.depart_date})")

        # 1. Fetch current price
        offer = self.client.fetch_cheapest_offer(flight)
        if offer is None:
            print(f"[Monitor] No se pudo obtener precio para {route}. Reintentara en el proximo ciclo.")
            return

        category_label = "LOW" if offer.price_category == "best" else "OTHER"
        print(
            f"[Monitor] Precio encontrado: {offer.currency} {offer.price:,.0f} "
            f"({offer.airline}, {offer.stops} escala(s)) [{category_label}]"
        )

        # 2. Get price statistics BEFORE inserting
        stats = self.storage.get_price_stats(
            flight.origin, flight.destination, flight.depart_date
        )

        # 3. Save to history
        self.storage.insert_price(offer)

        # 4. Show statistics
        if stats.avg_low_price:
            discount_pct = self.calculate_discount(offer.price, stats.avg_low_price)
            print(f"[Monitor] Promedio LOW historico: {offer.currency} {stats.avg_low_price:,.0f} ({stats.count_low} registros)")
            if discount_pct > 0:
                print(f"[Monitor] Precio actual esta {discount_pct:.1f}% POR DEBAJO del promedio LOW")
            else:
                print(f"[Monitor] Precio actual esta {abs(discount_pct):.1f}% POR ENCIMA del promedio LOW")
        else:
            print(f"[Monitor] Sin historial de precios LOW aun. Acumulando datos...")

        # 5. Decide whether to notify (only if 10%+ below average LOW)
        should_notify, discount_pct = self.should_alert(offer.price, stats)

        if should_notify:
            print(f"[Monitor] *** ALERTA! {discount_pct:.1f}% por debajo del promedio LOW ***")
            self._notify_all(offer, stats, discount_pct)
        else:
            if stats.avg_low_price:
                print(f"[Monitor] No se envia alerta (umbral: {ALERT_DISCOUNT_THRESHOLD}% bajo promedio LOW)")
            else:
                print(f"[Monitor] No se envia alerta (acumulando historial LOW)")

    async def check_all_flights_async(self) -> None:
        """Check all configured flights concurrently."""
        if not self.config.flights:
            print("[Monitor] No hay vuelos configurados.")
            return

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=len(self.config.flights)) as executor:
            tasks = [
                loop.run_in_executor(executor, self.check_flight, flight)
                for flight in self.config.flights
            ]
            await asyncio.gather(*tasks)

    def check_all_flights(self) -> None:
        """Check all configured flights (sync wrapper)."""
        asyncio.run(self.check_all_flights_async())

    def print_history(self) -> None:
        """Print recent price history for all flights."""
        for flight in self.config.flights:
            route = f"{flight.origin} -> {flight.destination}"
            rows = self.storage.get_price_history(
                flight.origin, flight.destination, flight.depart_date, limit=10
            )
            stats = self.storage.get_price_stats(
                flight.origin, flight.destination, flight.depart_date
            )

            if not rows:
                print(f"\n[{route}] Sin historial previo.")
                continue

            print(f"\n--- {route} ({flight.depart_date}) ---")
            if stats.avg_low_price:
                print(f"    Promedio LOW: {rows[0].currency} {stats.avg_low_price:,.0f} ({stats.count_low} registros)")
            print(f"    Ultimos {len(rows)} registros:")
            for record in rows:
                cat = "LOW" if record.price_category == "best" else "   "
                print(
                    f"      {record.checked_at[:16]}  {record.currency} {record.price:,.0f}  "
                    f"({record.airline}) [{cat}]"
                )

    async def run_async(self) -> None:
        """Main async loop that checks prices at configured intervals."""
        print("=" * 50)
        print("  Flight Monitor (SerpApi)")
        print(f"  Monitoreando {len(self.config.flights)} vuelo(s)")
        print(f"  Alerta: cuando precio este {ALERT_DISCOUNT_THRESHOLD}%+ bajo promedio LOW")
        print(f"  Intervalo: cada {self.config.check_interval_minutes} minutos")
        print("=" * 50)

        # Show previous history
        self.print_history()

        # Initial check
        await self.check_all_flights_async()

        print(
            f"\n[Monitor] Corriendo. Proximo chequeo en "
            f"{self.config.check_interval_minutes} min. Ctrl+C para detener.\n"
        )

        # Periodic checks
        while True:
            await asyncio.sleep(self.config.check_interval_minutes * 60)
            await self.check_all_flights_async()

    def run(self) -> None:
        """Main entry point (sync wrapper) - continuous mode."""
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            print("\n[Monitor] Detenido por el usuario.")

    def run_once(self) -> None:
        """Run a single check and exit (for cron jobs)."""
        print("=" * 50)
        print("  Flight Monitor (SerpApi) - Modo unico")
        print(f"  Chequeando {len(self.config.flights)} vuelo(s)")
        print(f"  Alerta: cuando precio este {ALERT_DISCOUNT_THRESHOLD}%+ bajo promedio LOW")
        print("=" * 50)

        # Run single check
        self.check_all_flights()

        print("\n[Monitor] Chequeo completado.")
