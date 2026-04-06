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

    def fetch_cheapest_offer(self, flight: FlightConfig) -> Optional[FlightOffer]:
        """
        Query Google Flights via SerpApi and return the cheapest flight found.

        Args:
            flight: Flight configuration with search parameters

        Returns:
            FlightOffer with price details and category, or None if error/not found
        """
        params = {
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
                print(f"[SerpApi] No se encontraron vuelos para {flight.origin}->{flight.destination}")
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
                if cheapest is None or cheapest_other.get("price", float("inf")) < cheapest.get("price", float("inf")):
                    cheapest = cheapest_other
                    price_category = "other"

            if cheapest is None:
                print(f"[SerpApi] No se encontraron vuelos validos")
                return None

            price = cheapest.get("price", 0)

            # Extract flight details from first leg
            flights_info = cheapest.get("flights", [])
            if not flights_info:
                print(f"[SerpApi] Respuesta sin detalles de vuelo")
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

            category_label = "LOW" if price_category == "best" else "OTHER"
            print(f"[SerpApi] Categoria de precio: {category_label}")

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
                price_category=price_category,
            )

        except requests.exceptions.RequestException as e:
            print(f"[SerpApi] Error de conexion: {e}")
            return None
        except (KeyError, ValueError, TypeError) as e:
            print(f"[SerpApi] Error procesando respuesta: {e}")
            return None
        except Exception as e:
            print(f"[SerpApi] Error inesperado: {e}")
            return None
