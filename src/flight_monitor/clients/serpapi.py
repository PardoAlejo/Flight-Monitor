"""SerpApi client for Google Flights searches."""

from dataclasses import dataclass
from typing import Optional

import requests

from ..config import FlightConfig
from ..notifiers.base import FlightOffer


@dataclass(frozen=True)
class SerpApiAccountStatus:
    """Current SerpApi quota and usage summary."""

    plan_name: Optional[str]
    plan_monthly_price: Optional[float]
    searches_per_month: Optional[int]
    plan_searches_left: Optional[int]
    extra_credits: Optional[int]
    total_searches_left: Optional[int]
    this_month_usage: Optional[int]
    last_hour_searches: Optional[int]
    account_rate_limit_per_hour: Optional[int]

    @property
    def remaining_searches(self) -> Optional[int]:
        """Return the best available remaining-search count."""
        if self.total_searches_left is not None:
            return self.total_searches_left
        return self.plan_searches_left


class SerpApiClient:
    """Client for querying flight prices from Google Flights via SerpApi."""

    BASE_URL = "https://serpapi.com/search"
    ACCOUNT_URL = "https://serpapi.com/account.json"

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

    def fetch_account_status(self) -> Optional[SerpApiAccountStatus]:
        """Fetch the current SerpApi account usage and remaining quota."""
        try:
            response = requests.get(
                self.ACCOUNT_URL,
                params={"api_key": self.api_key},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()

            return SerpApiAccountStatus(
                plan_name=data.get("plan_name"),
                plan_monthly_price=(
                    float(data["plan_monthly_price"])
                    if data.get("plan_monthly_price") is not None
                    else None
                ),
                searches_per_month=(
                    int(data["searches_per_month"])
                    if data.get("searches_per_month") is not None
                    else None
                ),
                plan_searches_left=(
                    int(data["plan_searches_left"])
                    if data.get("plan_searches_left") is not None
                    else None
                ),
                extra_credits=(
                    int(data["extra_credits"])
                    if data.get("extra_credits") is not None
                    else None
                ),
                total_searches_left=(
                    int(data["total_searches_left"])
                    if data.get("total_searches_left") is not None
                    else None
                ),
                this_month_usage=(
                    int(data["this_month_usage"])
                    if data.get("this_month_usage") is not None
                    else None
                ),
                last_hour_searches=(
                    int(data["last_hour_searches"])
                    if data.get("last_hour_searches") is not None
                    else None
                ),
                account_rate_limit_per_hour=(
                    int(data["account_rate_limit_per_hour"])
                    if data.get("account_rate_limit_per_hour") is not None
                    else None
                ),
            )
        except requests.exceptions.RequestException as e:
            print(f"[SerpApi] Error consultando cuota: {self._sanitize_error(e)}")
            return None
        except (KeyError, ValueError, TypeError) as e:
            print(f"[SerpApi] Error procesando cuota: {e}")
            return None

    @staticmethod
    def _has_excluded_layover(
        flight_data: dict[str, object], excluded: set[str]
    ) -> bool:
        """Check if a flight routes through any excluded layover airport."""
        segments = flight_data.get("flights", [])
        if not isinstance(segments, list) or len(segments) <= 1:
            return False
        # Check intermediate airports (skip first departure and last arrival)
        for seg in segments[:-1]:
            if not isinstance(seg, dict):
                continue
            arrival = seg.get("arrival_airport", {})
            if isinstance(arrival, dict) and arrival.get("id") in excluded:
                return True
        return False

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

            # Filter out flights with excluded layover airports
            excluded = set(flight.exclude_layover_airports)
            if excluded:
                best_flights = [
                    f for f in best_flights
                    if not self._has_excluded_layover(f, excluded)
                ]
                other_flights = [
                    f for f in other_flights
                    if not self._has_excluded_layover(f, excluded)
                ]

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
                dep_time = departure.get("time", "")
                arr_time = arrival.get("time", "")
                segments.append(
                    f"{departure.get('id', '?')} -> {arrival.get('id', '?')}"
                    f" ({dep_time} -> {arr_time})"
                )

            # Departure and arrival times (overall journey)
            departure_time = flights_info[0].get(
                "departure_airport", {}
            ).get("time")
            arrival_time = flights_info[-1].get(
                "arrival_airport", {}
            ).get("time")

            # Layover details
            layover_list: list[str] = []
            for layover in cheapest.get("layovers", []):
                lay_duration = layover.get("duration", 0)
                lay_id = layover.get("id", "?")
                hours = lay_duration // 60
                minutes = lay_duration % 60
                if hours > 0 and minutes > 0:
                    lay_fmt = f"{hours}h {minutes}m"
                elif hours > 0:
                    lay_fmt = f"{hours}h"
                else:
                    lay_fmt = f"{minutes}m"
                layover_list.append(f"{lay_fmt} en {lay_id}")

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
                departure_time=departure_time,
                arrival_time=arrival_time,
                layovers=layover_list,
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
