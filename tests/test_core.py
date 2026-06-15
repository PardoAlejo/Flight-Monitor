"""Functional tests for the main Flight Monitor workflows."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from flight_monitor.clients.serpapi import SerpApiClient
from flight_monitor.config import AppConfig, FlightConfig
from flight_monitor.monitor import FlightMonitor
from flight_monitor.notifiers.base import FlightCheckResult, FlightOffer, Notifier, TrendInfo
from flight_monitor.scheduler import RetryScheduler
from flight_monitor.storage.sqlite import PriceStats, SQLiteStorage


class FakeClient:
    """Return a predefined offer without making network requests."""

    def __init__(self, offer: FlightOffer | None):
        self.offer = offer

    def fetch_cheapest_offer(self, flight: FlightConfig) -> FlightOffer | None:
        return self.offer


class RecordingNotifier(Notifier):
    """Capture summaries instead of sending them externally."""

    def __init__(self, succeeds: bool = True):
        self.succeeds = succeeds
        self.summaries: list[list[FlightCheckResult]] = []

    def is_configured(self) -> bool:
        return True

    def send_summary(self, results: list[FlightCheckResult]) -> bool:
        self.summaries.append(results)
        return self.succeeds


class SerpApiClientTests(unittest.TestCase):
    @patch("flight_monitor.clients.serpapi.requests.get")
    def test_fetch_account_status_prefers_total_remaining(self, mock_get: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "plan_name": "Free",
            "plan_searches_left": 20,
            "extra_credits": 5,
            "total_searches_left": 25,
            "this_month_usage": 10,
        }
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        status = SerpApiClient("secret").fetch_account_status()

        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status.remaining_searches, 25)
        mock_get.assert_called_once_with(
            SerpApiClient.ACCOUNT_URL,
            params={"api_key": "secret"},
            timeout=15,
        )

    @patch("flight_monitor.clients.serpapi.requests.get")
    def test_fetch_cheapest_offer_parses_cheapest_result(self, mock_get: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "best_flights": [
                {
                    "price": 500,
                    "total_duration": 180,
                    "flights": [
                        {
                            "airline": "Air One",
                            "departure_airport": {"id": "BOG", "time": "08:00"},
                            "arrival_airport": {"id": "MIA"},
                        }
                    ],
                }
            ],
            "other_flights": [
                {
                    "price": 450,
                    "total_duration": 240,
                    "flights": [
                        {
                            "airline": "Air Two",
                            "departure_airport": {"id": "BOG", "time": "09:00"},
                            "arrival_airport": {"id": "PTY"},
                        },
                        {
                            "airline": "Air Two",
                            "departure_airport": {"id": "PTY", "time": "12:00"},
                            "arrival_airport": {"id": "MIA"},
                        },
                    ],
                }
            ],
            "price_insights": {
                "typical_price_range": [480, 650],
                "price_level": "low",
            },
        }
        response.raise_for_status.return_value = None
        mock_get.return_value = response
        flight = FlightConfig(
            origin="BOG",
            destination="MIA",
            depart_date="2026-12-01",
            return_date="2026-12-15",
            adults=2,
            currency="USD",
        )

        offer = SerpApiClient("secret").fetch_cheapest_offer(flight)

        self.assertIsNotNone(offer)
        assert offer is not None
        self.assertEqual(offer.price, 450)
        self.assertEqual(offer.airline, "Air Two")
        self.assertEqual(offer.stops, 1)
        self.assertEqual(offer.price_category, "other")
        self.assertEqual(offer.typical_price_low, 480)
        self.assertEqual(offer.typical_price_high, 650)
        self.assertEqual(offer.price_level, "low")
        self.assertEqual(offer.price_per_person, 225)


class FlightMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = str(Path(self.temp_dir.name) / "prices.db")
        self.flight = FlightConfig(
            origin="BOG",
            destination="MIA",
            depart_date="2026-12-01",
            return_date="2026-12-15",
        )
        self.config = AppConfig(
            serpapi_key="unused",
            db_path=self.db_path,
            flights=[self.flight],
        )

    def test_run_once_persists_offer_and_sends_recommendation(self) -> None:
        offer = FlightOffer(
            price=400,
            currency="USD",
            airline="Test Air",
            segments=["BOG -> MIA (08:00)"],
            stops=0,
            origin="BOG",
            destination="MIA",
            depart_date="2026-12-01",
            return_date="2026-12-15",
            typical_price_low=500,
            typical_price_high=650,
            price_level="low",
        )
        notifier = RecordingNotifier()
        storage = SQLiteStorage(self.db_path)
        monitor = FlightMonitor(
            self.config,
            FakeClient(offer),
            storage,
            [notifier],
        )

        succeeded = monitor.run_once()

        self.assertTrue(succeeded)
        history = storage.get_price_history("BOG", "MIA", "2026-12-01")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].price, 400)
        self.assertEqual(len(notifier.summaries), 1)
        result = notifier.summaries[0][0]
        self.assertTrue(result.succeeded)
        self.assertTrue(result.recommended)
        self.assertEqual(result.discount_pct, 20)

    def test_run_once_fails_when_provider_returns_no_offer(self) -> None:
        notifier = RecordingNotifier()
        monitor = FlightMonitor(
            self.config,
            FakeClient(None),
            SQLiteStorage(self.db_path),
            [notifier],
        )

        succeeded = monitor.run_once()

        self.assertFalse(succeeded)
        self.assertEqual(len(notifier.summaries), 1)
        self.assertFalse(notifier.summaries[0][0].succeeded)


class MultiOfferClient:
    """Return different offers depending on the depart_date."""

    def __init__(self, offers_by_date: dict[str, FlightOffer | None]):
        self.offers_by_date = offers_by_date

    def fetch_cheapest_offer(self, flight: FlightConfig) -> FlightOffer | None:
        return self.offers_by_date.get(flight.depart_date)


class DateFlexibilityTests(unittest.TestCase):
    def test_expand_dates_no_flexibility(self) -> None:
        flight = FlightConfig(
            origin="BOG", destination="MIA",
            depart_date="2027-06-10", return_date="2027-06-20",
        )
        variants = FlightMonitor.expand_dates(flight)
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0].depart_date, "2027-06-10")

    def test_expand_dates_with_flexibility(self) -> None:
        flight = FlightConfig(
            origin="BOG", destination="MIA",
            depart_date="2027-06-10", return_date="2027-06-20",
            date_flexibility=2,
        )
        variants = FlightMonitor.expand_dates(flight)
        # 5 variants: -2, -1, 0, +1, +2
        self.assertEqual(len(variants), 5)
        self.assertEqual(variants[0].depart_date, "2027-06-08")
        self.assertEqual(variants[0].return_date, "2027-06-18")
        self.assertEqual(variants[2].depart_date, "2027-06-10")
        self.assertEqual(variants[2].return_date, "2027-06-20")
        self.assertEqual(variants[4].depart_date, "2027-06-12")
        self.assertEqual(variants[4].return_date, "2027-06-22")
        # All variants should have flexibility=0
        for v in variants:
            self.assertEqual(v.date_flexibility, 0)

    def test_expand_dates_forward_only(self) -> None:
        flight = FlightConfig(
            origin="BOG", destination="LHR",
            depart_date="2027-06-10", return_date="2027-09-10",
            date_flexibility=3, flexibility_direction="forward",
        )
        variants = FlightMonitor.expand_dates(flight)
        # 4 variants: 0, +1, +2, +3
        self.assertEqual(len(variants), 4)
        self.assertEqual(variants[0].depart_date, "2027-06-10")
        self.assertEqual(variants[0].return_date, "2027-09-10")
        self.assertEqual(variants[3].depart_date, "2027-06-13")
        self.assertEqual(variants[3].return_date, "2027-09-13")

    def test_expand_dates_one_way(self) -> None:
        flight = FlightConfig(
            origin="BOG", destination="MIA",
            depart_date="2027-06-10",
            date_flexibility=1,
        )
        variants = FlightMonitor.expand_dates(flight)
        self.assertEqual(len(variants), 3)
        self.assertIsNone(variants[0].return_date)

    def test_check_date_variants_picks_cheapest(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = str(Path(temp_dir.name) / "prices.db")

        flight = FlightConfig(
            origin="BOG", destination="MIA",
            depart_date="2027-06-10", return_date="2027-06-20",
            date_flexibility=1,
        )
        config = AppConfig(
            serpapi_key="unused", db_path=db_path, flights=[flight],
        )

        def make_offer(date: str, price: float) -> FlightOffer:
            return FlightOffer(
                price=price, currency="USD", airline="Test",
                segments=["BOG -> MIA"], stops=0,
                origin="BOG", destination="MIA",
                depart_date=date, return_date=None,
                typical_price_low=500, typical_price_high=650,
            )

        client = MultiOfferClient({
            "2027-06-09": make_offer("2027-06-09", 450),
            "2027-06-10": make_offer("2027-06-10", 380),
            "2027-06-11": make_offer("2027-06-11", 420),
        })

        notifier = RecordingNotifier()
        monitor = FlightMonitor(
            config, client, SQLiteStorage(db_path), [notifier],
        )

        result = monitor.check_flight(flight)

        self.assertTrue(result.succeeded)
        assert result.offer is not None
        self.assertEqual(result.offer.price, 380)
        self.assertEqual(result.offer.depart_date, "2027-06-10")
        self.assertTrue(result.recommended)  # 380 < 500 typical_low
        self.assertEqual(len(result.date_alternatives), 3)
        cheapest_alt = [a for a in result.date_alternatives if a.is_cheapest]
        self.assertEqual(len(cheapest_alt), 1)
        self.assertEqual(cheapest_alt[0].depart_date, "2027-06-10")


class TrendAnalysisTests(unittest.TestCase):
    def test_compute_trend_no_history(self) -> None:
        trend = FlightMonitor.compute_trend(400, None)
        self.assertIsNone(trend)

    def test_compute_trend_with_history(self) -> None:
        stats = PriceStats(
            record_count=5,
            min_price=380,
            avg_price=450,
            previous_price=420,
            previous_checked_at="2026-06-14T10:00:00",
        )
        trend = FlightMonitor.compute_trend(400, stats)

        self.assertIsNotNone(trend)
        assert trend is not None
        self.assertEqual(trend.record_count, 5)
        self.assertEqual(trend.historical_min, 380)
        self.assertEqual(trend.historical_avg, 450)
        # 400 - 420 = -20
        self.assertEqual(trend.price_change, -20)
        self.assertAlmostEqual(trend.price_change_pct, -4.76, places=1)
        # (400 - 450) / 450 * 100 ≈ -11.1%
        self.assertAlmostEqual(trend.vs_avg_pct, -11.1, places=1)
        # 400 > 380, so not all-time low
        self.assertFalse(trend.is_all_time_low)

    def test_compute_trend_all_time_low(self) -> None:
        stats = PriceStats(
            record_count=3,
            min_price=420,
            avg_price=500,
            previous_price=450,
            previous_checked_at="2026-06-14T10:00:00",
        )
        trend = FlightMonitor.compute_trend(350, stats)

        assert trend is not None
        self.assertTrue(trend.is_all_time_low)
        self.assertEqual(trend.price_change, -100)

    def test_price_stats_from_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "prices.db")
            storage = SQLiteStorage(db_path)

            # No history yet
            self.assertIsNone(storage.get_price_stats("BOG", "MIA", "2027-01-01"))

            # Insert some prices
            for price in [500, 450, 480]:
                storage.insert_price(FlightOffer(
                    price=price, currency="USD", airline="Test",
                    segments=["BOG -> MIA"], stops=0,
                    origin="BOG", destination="MIA",
                    depart_date="2027-01-01",
                ))

            stats = storage.get_price_stats("BOG", "MIA", "2027-01-01")
            self.assertIsNotNone(stats)
            assert stats is not None
            self.assertEqual(stats.record_count, 3)
            self.assertEqual(stats.min_price, 450)
            self.assertAlmostEqual(stats.avg_price, 476.67, places=1)
            # Most recent is 480
            self.assertEqual(stats.previous_price, 480)

    def test_check_flight_includes_trend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "prices.db")
            flight = FlightConfig(
                origin="BOG", destination="MIA", depart_date="2027-01-01",
            )
            config = AppConfig(
                serpapi_key="unused", db_path=db_path, flights=[flight],
            )
            storage = SQLiteStorage(db_path)

            # Seed history
            storage.insert_price(FlightOffer(
                price=500, currency="USD", airline="Old",
                segments=["BOG -> MIA"], stops=0,
                origin="BOG", destination="MIA", depart_date="2027-01-01",
            ))

            offer = FlightOffer(
                price=420, currency="USD", airline="Test",
                segments=["BOG -> MIA"], stops=0,
                origin="BOG", destination="MIA", depart_date="2027-01-01",
                typical_price_low=500, typical_price_high=650,
            )
            monitor = FlightMonitor(
                config, FakeClient(offer), storage, [RecordingNotifier()],
            )

            result = monitor.check_flight(flight)

            self.assertIsNotNone(result.trend)
            assert result.trend is not None
            self.assertTrue(result.trend.is_all_time_low)
            self.assertEqual(result.trend.price_change, -80)


class RetrySchedulerTests(unittest.TestCase):
    def test_failed_slot_waits_then_retries_and_stops_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "scheduler.json"
            scheduler = RetryScheduler(
                str(state_path),
                ["11:00"],
                retry_delay_minutes=60,
            )
            scheduled_time = datetime(2026, 6, 15, 11, 0)

            slot = scheduler.next_due_slot(scheduled_time)
            self.assertIsNotNone(slot)
            assert slot is not None

            scheduler.mark_attempt(slot, scheduled_time, succeeded=False)
            self.assertIsNone(scheduler.next_due_slot(scheduled_time + timedelta(minutes=59)))

            retry_time = scheduled_time + timedelta(minutes=60)
            self.assertEqual(scheduler.next_due_slot(retry_time), slot)

            scheduler.mark_attempt(slot, retry_time, succeeded=True)
            self.assertIsNone(scheduler.next_due_slot(retry_time + timedelta(hours=1)))

            state = json.loads(state_path.read_text())
            self.assertEqual(state[slot.slot_id]["last_status"], "success")
            self.assertIn("completed_at", state[slot.slot_id])


if __name__ == "__main__":
    unittest.main()
