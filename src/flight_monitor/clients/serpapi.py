"""SerpApi client for Google Flights searches."""

from typing import Optional

import requests

from ..config import FlightConfig
from ..notifiers.base import FlightOffer


class SerpApiClient:
    """Client for querying flight prices from Google Flights via SerpApi."""

    BASE_URL = "https://serpapi.com/search"

    def __init__(self, api_key: str):
        """
        Initialize the SerpApi client.

        Args:
            api_key: SerpApi API key
        """
        self.api_key = api_key

    def _sanitize_error(self, error: Exception) -> str:
        """Remove secrets from exception messages before logging them."""
        return str(error).replace(self.api_key, "***REDACTED***")

    def fetch_cheapest_offer(self, flight: FlightConfig) -> Optional[FlightOffer]:
        """
        Query Google Flights via SerpApi and return the cheapest flight found.

        Args:
            flight: Flight configuration with search parameters

        Returns:
            FlightOffer with price details and category, or None if error/not found
        """
        params: dict[str, str | int] = {
            "engine": "google_flights",
            "api_key": self.api_key,
            "departure_id": flight.origin,
            "arrival_id": flight.destination,
            "outbound_date": flight.depart_date,
            "adults": flight.adults,
            "currency": flight.currency,
            "type": "1" if flight.return_date else "2",  # 1=round trip, 2=one way
            "hl": "es",  # Spanish
        }

        if flight.return_date:
            params["return_date"] = flight.return_date

        try:
            response = requests.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Check for errors in response
            if "error" in data:
                print(f"[SerpApi] Error: {data['error']}")
                return None

            # Get best flights (LOW category) and other flights
            best_flights = data.get("best_flights", [])
            other_flights = data.get("other_flights", [])

            if not best_flights and not other_flights:
                print(f"[SerpApi] No hay vuelos {flight.origin}->{flight.destination}")
                return None

            # Find cheapest from best_flights first (these are LOW category)
            cheapest = None
            price_category = "other"

            if best_flights:
                cheapest = min(best_flights, key=lambda f: f.get("price", float("inf")))
                price_category = "best"  # LOW category

            # Check if there's a cheaper one in other_flights
            if other_flights:
                cheapest_other = min(other_flights, key=lambda f: f.get("price", float("inf")))
                other_price = cheapest_other.get("price", float("inf"))
                current_price = cheapest.get("price", float("inf")) if cheapest else float("inf")
                if cheapest is None or other_price < current_price:
                    cheapest = cheapest_other
                    price_category = "other"

            if cheapest is None:
                print("[SerpApi] No se encontraron vuelos validos")
                return None

            price = cheapest.get("price", 0)

            # Extract flight details from first leg
            flights_info = cheapest.get("flights", [])
            if not flights_info:
                print("[SerpApi] Respuesta sin detalles de vuelo")
                return None

            first_flight = flights_info[0]
            airline = first_flight.get("airline", "Unknown")

            # Build segment summary
            segments = []
            for seg in flights_info:
                departure = seg.get("departure_airport", {})
                arrival = seg.get("arrival_airport", {})
                dep_time = seg.get("departure_airport", {}).get("time", "")
                segments.append(
                    f"{departure.get('id', '?')} -> {arrival.get('id', '?')} ({dep_time})"
                )

            # Calculate stops
            stops = len(flights_info) - 1

            # Extract total duration (in minutes)
            total_duration = cheapest.get("total_duration")

            category_label = "LOW" if price_category == "best" else "OTHER"
            print(f"[SerpApi] Categoria de precio: {category_label}")

            # Extract price insights from Google
            price_insights = data.get("price_insights", {})
            typical_range = price_insights.get("typical_price_range", [None, None])
            typical_low = typical_range[0] if len(typical_range) > 0 else None
            typical_high = typical_range[1] if len(typical_range) > 1 else None
            price_level = price_insights.get("price_level")

            if typical_low and typical_high:
                low_fmt, high_fmt = f"{typical_low:,.0f}", f"{typical_high:,.0f}"
                print(f"[SerpApi] Rango tipico Google: {flight.currency} {low_fmt} - {high_fmt}")
            if price_level:
                print(f"[SerpApi] Nivel de precio Google: {price_level.upper()}")

            return FlightOffer(
                price=float(price),
                currency=flight.currency,
                airline=airline,
                segments=segments,
                stops=stops,
                origin=flight.origin,
                destination=flight.destination,
                depart_date=flight.depart_date,
                return_date=flight.return_date,
                adults=flight.adults,
                price_category=price_category,
                total_duration=int(total_duration) if total_duration else None,
                typical_price_low=float(typical_low) if typical_low else None,
                typical_price_high=float(typical_high) if typical_high else None,
                price_level=price_level,
            )

        except requests.exceptions.RequestException as e:
            print(f"[SerpApi] Error de conexion: {self._sanitize_error(e)}")
            return None
        except (KeyError, ValueError, TypeError) as e:
            print(f"[SerpApi] Error procesando respuesta: {e}")
            return None
        except Exception as e:
            print(f"[SerpApi] Error inesperado: {e}")
            return None
