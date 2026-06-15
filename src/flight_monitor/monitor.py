"""Flight price monitor with support for multiple flights."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

from .config import AppConfig, FlightConfig
from .notifiers.base import DateAlternative, FlightCheckResult, FlightOffer, Notifier, TrendInfo
from .storage.sqlite import PriceStats, SQLiteStorage


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

    def calculate_discount(self, current_price: float, typical_low: float) -> float:
        """
        Calculate the percentage discount from Google's typical low price.

        Args:
            current_price: Current flight price
            typical_low: Google's typical price range lower bound

        Returns:
            Discount percentage (positive means cheaper than typical)
        """
        if typical_low <= 0:
            return 0.0
        return ((typical_low - current_price) / typical_low) * 100

    def should_recommend(self, offer: FlightOffer) -> tuple[bool, float]:
        """
        Determine if purchase should be recommended based on Google's typical price range.

        Recommend if price is below the typical price range lower bound.

        Args:
            offer: Flight offer with price insights from Google

        Returns:
            Tuple of (should_recommend, discount_percentage)
        """
        if offer.typical_price_low is None:
            return False, 0.0

        discount_pct = self.calculate_discount(offer.price, offer.typical_price_low)

        # Recommend if price is below typical low (discount_pct > 0)
        should_buy = discount_pct > 0

        return should_buy, discount_pct

    @staticmethod
    def compute_trend(price: float, stats: Optional[PriceStats]) -> Optional[TrendInfo]:
        """Build TrendInfo from current price and historical stats."""
        if stats is None or stats.record_count == 0:
            return None

        trend = TrendInfo(record_count=stats.record_count)
        trend.historical_min = stats.min_price
        trend.historical_avg = stats.avg_price

        # vs previous check
        if stats.previous_price is not None:
            trend.price_change = price - stats.previous_price
            if stats.previous_price > 0:
                trend.price_change_pct = (
                    (price - stats.previous_price) / stats.previous_price
                ) * 100

        # vs average
        if stats.avg_price > 0:
            trend.vs_avg_pct = ((price - stats.avg_price) / stats.avg_price) * 100

        # all-time low (strictly less than any previously recorded price)
        trend.is_all_time_low = price < stats.min_price

        return trend

    def _get_trend(self, offer: FlightOffer) -> Optional[TrendInfo]:
        """Query history and compute trend for an offer."""
        stats = self.storage.get_price_stats(
            offer.origin, offer.destination, offer.depart_date
        )
        return self.compute_trend(offer.price, stats)

    def _print_trend(self, trend: Optional[TrendInfo], currency: str) -> None:
        """Print trend info to console."""
        if trend is None or trend.record_count == 0:
            return

        parts = []
        if trend.price_change is not None and trend.price_change != 0:
            direction = "↓" if trend.price_change < 0 else "↑"
            parts.append(
                f"{direction} {currency} {abs(trend.price_change):,.0f} vs anterior"
            )
        if trend.vs_avg_pct is not None:
            if trend.vs_avg_pct < 0:
                parts.append(f"{abs(trend.vs_avg_pct):.0f}% bajo promedio historico")
            else:
                parts.append(f"{trend.vs_avg_pct:.0f}% sobre promedio historico")
        if trend.is_all_time_low:
            parts.append("MINIMO HISTORICO")

        if parts:
            print(f"[Tendencia] {' | '.join(parts)} ({trend.record_count} registros)")

    @staticmethod
    def expand_dates(flight: FlightConfig) -> list[FlightConfig]:
        """
        Expand a flight config into multiple configs for each date variant.

        Shifts depart_date by -N to +N days (where N = date_flexibility),
        keeping trip duration constant (return_date shifts by the same offset).
        """
        if flight.date_flexibility <= 0:
            return [flight]

        base_depart = datetime.strptime(flight.depart_date, "%Y-%m-%d")
        trip_days: int | None = None
        if flight.return_date:
            base_return = datetime.strptime(flight.return_date, "%Y-%m-%d")
            trip_days = (base_return - base_depart).days

        variants: list[FlightConfig] = []
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        for offset in range(-flight.date_flexibility, flight.date_flexibility + 1):
            new_depart = base_depart + timedelta(days=offset)
            # Skip dates in the past
            if new_depart < today:
                continue

            new_return: str | None = None
            if trip_days is not None:
                new_return = (new_depart + timedelta(days=trip_days)).strftime("%Y-%m-%d")

            variants.append(FlightConfig(
                origin=flight.origin,
                destination=flight.destination,
                depart_date=new_depart.strftime("%Y-%m-%d"),
                return_date=new_return,
                adults=flight.adults,
                currency=flight.currency,
                date_flexibility=0,  # Don't re-expand
            ))

        return variants

    def _check_date_variants(self, flight: FlightConfig) -> FlightCheckResult:
        """
        Check all date variants for a flight and return the best result.

        Searches ±date_flexibility days around the configured dates,
        picks the cheapest offer, and includes a date-price comparison.
        """
        variants = self.expand_dates(flight)
        route = f"{flight.origin} -> {flight.destination}"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        print(f"\n{'='*50}")
        print(
            f"[{now}] Chequeando {route} ({flight.depart_date}) "
            f"± {flight.date_flexibility} dias ({len(variants)} fechas)"
        )

        # Search all date variants
        offers: list[tuple[FlightConfig, FlightOffer]] = []
        for variant in variants:
            offer = self.client.fetch_cheapest_offer(variant)
            if offer is not None:
                offers.append((variant, offer))
                self.storage.insert_price(offer)
                print(
                    f"  [{variant.depart_date}] {offer.currency} {offer.price:,.0f} "
                    f"({offer.airline})"
                )
            else:
                print(f"  [{variant.depart_date}] Sin resultados")

        if not offers:
            print(f"[Monitor] No se encontraron vuelos para ninguna fecha en {route}")
            return FlightCheckResult(
                origin=flight.origin,
                destination=flight.destination,
                depart_date=flight.depart_date,
                return_date=flight.return_date,
                error_message="No se encontraron vuelos en ninguna fecha del rango.",
            )

        # Find cheapest
        best_variant, best_offer = min(offers, key=lambda x: x[1].price)

        # Build date alternatives list
        date_alternatives = [
            DateAlternative(
                depart_date=v.depart_date,
                return_date=v.return_date,
                price=o.price,
                currency=o.currency,
                is_cheapest=(v.depart_date == best_variant.depart_date),
            )
            for v, o in sorted(offers, key=lambda x: x[0].depart_date)
        ]

        print(
            f"[Monitor] Mejor fecha: {best_variant.depart_date} "
            f"- {best_offer.currency} {best_offer.price:,.0f}"
        )

        # Compute trend for the best offer's date
        trend = self._get_trend(best_offer)

        # Evaluate recommendation on best offer
        should_buy, discount_pct = self.should_recommend(best_offer)

        if best_offer.typical_price_low:
            if discount_pct > 0:
                print(f"[Monitor] Precio {discount_pct:.1f}% POR DEBAJO del rango tipico")
            else:
                print(f"[Monitor] Precio {abs(discount_pct):.1f}% por encima del rango tipico")
            if should_buy:
                print("[Monitor] *** RECOMENDADO COMPRAR ***")
            else:
                print("[Monitor] Esperar mejor precio")

        self._print_trend(trend, best_offer.currency)

        return FlightCheckResult(
            origin=flight.origin,
            destination=flight.destination,
            depart_date=best_offer.depart_date,
            return_date=best_offer.return_date,
            offer=best_offer,
            discount_pct=discount_pct,
            recommended=should_buy,
            date_alternatives=date_alternatives,
            trend=trend,
        )

    def check_flight(self, flight: FlightConfig) -> FlightCheckResult:
        """
        Check price for a single flight.

        Args:
            flight: Flight configuration to check

        Returns:
            FlightCheckResult with offer details or failure metadata
        """
        # Delegate to date-variant search when flexibility is configured
        if flight.date_flexibility > 0:
            return self._check_date_variants(flight)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        route = f"{flight.origin} -> {flight.destination}"
        print(f"\n{'='*50}")
        print(f"[{now}] Chequeando {route} ({flight.depart_date})")

        # 1. Fetch current price with Google's price insights
        offer = self.client.fetch_cheapest_offer(flight)
        if offer is None:
            print(f"[Monitor] No se pudo obtener precio para {route}.")
            return FlightCheckResult(
                origin=flight.origin,
                destination=flight.destination,
                depart_date=flight.depart_date,
                return_date=flight.return_date,
                error_message="No se pudo obtener precio desde SerpApi.",
            )

        category_label = "LOW" if offer.price_category == "best" else "OTHER"
        if offer.adults > 1:
            total = f"{offer.currency} {offer.price:,.0f}"
            per_person = f"{offer.currency} {offer.price_per_person:,.0f}"
            print(
                f"[Monitor] Precio: {total} ({per_person}/persona, {offer.adults} pax) "
                f"[{offer.airline}, {offer.stops} escala(s), {category_label}]"
            )
        else:
            print(
                f"[Monitor] Precio encontrado: {offer.currency} {offer.price:,.0f} "
                f"({offer.airline}, {offer.stops} escala(s)) [{category_label}]"
            )

        # 2. Compute trend from history (before saving current price)
        trend = self._get_trend(offer)

        # 3. Save to history
        self.storage.insert_price(offer)

        # 4. Compare with Google's typical price range
        should_buy, discount_pct = self.should_recommend(offer)

        if offer.typical_price_low:
            if discount_pct > 0:
                print(f"[Monitor] Precio {discount_pct:.1f}% POR DEBAJO del rango tipico")
            else:
                print(f"[Monitor] Precio {abs(discount_pct):.1f}% por encima del rango tipico")

            if should_buy:
                print("[Monitor] *** RECOMENDADO COMPRAR ***")
            else:
                print("[Monitor] Esperar mejor precio")
        else:
            print("[Monitor] Google no proporciono rango tipico para esta ruta")

        self._print_trend(trend, offer.currency)

        # Return result for summary
        return FlightCheckResult(
            origin=flight.origin,
            destination=flight.destination,
            depart_date=flight.depart_date,
            return_date=flight.return_date,
            offer=offer,
            discount_pct=discount_pct,
            recommended=should_buy,
            trend=trend,
        )

    async def check_all_flights_async(self) -> list[FlightCheckResult]:
        """Check all configured flights concurrently."""
        if not self.config.flights:
            print("[Monitor] No hay vuelos configurados.")
            return []

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=len(self.config.flights)) as executor:
            tasks = [
                loop.run_in_executor(executor, self.check_flight, flight)
                for flight in self.config.flights
            ]
            results = await asyncio.gather(*tasks)

        return results

    def check_all_flights(self) -> list[FlightCheckResult]:
        """Check all configured flights (sync wrapper)."""
        return asyncio.run(self.check_all_flights_async())

    def print_history(self) -> None:
        """Print recent price history for all flights."""
        for flight in self.config.flights:
            route = f"{flight.origin} -> {flight.destination}"
            rows = self.storage.get_price_history(
                flight.origin, flight.destination, flight.depart_date, limit=10
            )

            if not rows:
                print(f"\n[{route}] Sin historial previo.")
                continue

            print(f"\n--- {route} ({flight.depart_date}) ---")
            print(f"    Ultimos {len(rows)} registros:")
            for record in rows:
                cat = "LOW" if record.price_category == "best" else "   "
                print(
                    f"      {record.checked_at[:16]}  {record.currency} {record.price:,.0f}  "
                    f"({record.airline}) [{cat}]"
                )

    def _send_summary(self, results: list[FlightCheckResult]) -> bool:
        """Send a summary through all configured notifiers."""
        summary_sent = True
        for notifier in self.notifiers:
            summary_sent = notifier.send_summary(results) and summary_sent
        return summary_sent

    async def run_async(self) -> None:
        """Main async loop that checks prices at configured intervals."""
        print("=" * 50)
        print("  Flight Monitor (SerpApi)")
        print(f"  Monitoreando {len(self.config.flights)} vuelo(s)")
        print("  Alerta: cuando precio < rango tipico de Google")
        print(f"  Intervalo: cada {self.config.check_interval_minutes} minutos")
        print("=" * 50)

        # Show previous history
        self.print_history()

        last_summary_date: Optional[str] = None

        # Initial check
        results = await self.check_all_flights_async()
        today = datetime.now().date().isoformat()
        self._send_summary(results)
        last_summary_date = today

        print(
            f"\n[Monitor] Corriendo. Proximo chequeo en "
            f"{self.config.check_interval_minutes} min. Ctrl+C para detener.\n"
        )

        # Periodic checks
        while True:
            await asyncio.sleep(self.config.check_interval_minutes * 60)
            results = await self.check_all_flights_async()
            today = datetime.now().date().isoformat()
            if today != last_summary_date:
                self._send_summary(results)
                last_summary_date = today

    def run(self) -> None:
        """Main entry point (sync wrapper) - continuous mode."""
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            print("\n[Monitor] Detenido por el usuario.")

    def run_once(self) -> bool:
        """Run a single check and exit (for cron jobs)."""
        print("=" * 50)
        print("  Flight Monitor (SerpApi) - Modo unico")
        print(f"  Chequeando {len(self.config.flights)} vuelo(s)")
        print("  Alerta: cuando precio < rango tipico de Google")
        print("=" * 50)

        # Run single check
        results = self.check_all_flights()

        # Send daily summary
        summary_sent = self._send_summary(results)

        print("\n[Monitor] Chequeo completado.")
        checks_ok = all(result.succeeded for result in results)
        run_ok = bool(results) and checks_ok and summary_sent
        if not run_ok:
            print("[Monitor] Ejecucion marcada para reintento.")
        return run_ok
