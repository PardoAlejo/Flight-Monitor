"""SQLite storage backend for price history."""

import sqlite3
import statistics
from datetime import datetime
from typing import Optional

from ..notifiers.base import FlightOffer, PriceRecord, PriceStats


class SQLiteStorage:
    """SQLite-based storage for flight price history."""

    def __init__(self, db_path: str = "flight_prices.db"):
        """
        Initialize SQLite storage.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        """Create the prices table if it doesn't exist."""
        with self._get_connection() as conn:
            # Create table with price_category column
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prices (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    origin          TEXT    NOT NULL,
                    destination     TEXT    NOT NULL,
                    depart_date     TEXT    NOT NULL,
                    return_date     TEXT,
                    price           REAL    NOT NULL,
                    currency        TEXT    NOT NULL,
                    airline         TEXT,
                    price_category  TEXT    DEFAULT 'other',
                    checked_at      TEXT    NOT NULL
                )
            """)

            # Add price_category column if it doesn't exist (migration)
            try:
                conn.execute("ALTER TABLE prices ADD COLUMN price_category TEXT DEFAULT 'other'")
            except sqlite3.OperationalError:
                pass  # Column already exists

            conn.commit()
        print(f"[DB] Base de datos inicializada: {self.db_path}")

    def insert_price(self, offer: FlightOffer) -> None:
        """
        Insert a price record for a flight offer.

        Args:
            offer: The flight offer to record
        """
        now = datetime.utcnow().isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO prices
                    (origin, destination, depart_date, return_date, price, currency, airline, price_category, checked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    offer.origin,
                    offer.destination,
                    offer.depart_date,
                    offer.return_date,
                    offer.price,
                    offer.currency,
                    offer.airline,
                    offer.price_category,
                    now,
                ),
            )
            conn.commit()
        category_label = "LOW" if offer.price_category == "best" else "OTHER"
        print(f"[DB] Precio guardado: {offer.currency} {offer.price:,.0f} ({offer.airline}) [{category_label}]")

    def get_price_stats(
        self, origin: str, destination: str, depart_date: str
    ) -> PriceStats:
        """
        Get price statistics for a route, including median of LOW (best) prices.

        Args:
            origin: Origin airport code
            destination: Destination airport code
            depart_date: Departure date

        Returns:
            PriceStats with median LOW price, min price, and count
        """
        with self._get_connection() as conn:
            # Get all "best" (LOW) category prices for median calculation
            rows_low = conn.execute(
                """
                SELECT price
                FROM prices
                WHERE origin = ? AND destination = ? AND depart_date = ?
                AND price_category = 'best'
                ORDER BY price
                """,
                (origin, destination, depart_date),
            ).fetchall()

            # Get overall minimum price
            row_min = conn.execute(
                """
                SELECT MIN(price)
                FROM prices
                WHERE origin = ? AND destination = ? AND depart_date = ?
                """,
                (origin, destination, depart_date),
            ).fetchone()

        # Calculate median of LOW prices
        low_prices = [r[0] for r in rows_low]
        median_low = statistics.median(low_prices) if low_prices else None
        count_low = len(low_prices)
        min_price = row_min[0] if row_min and row_min[0] else None

        return PriceStats(
            avg_low_price=median_low,  # Now stores median instead of average
            min_price=min_price,
            count_low=count_low,
        )

    def get_minimum_price(
        self, origin: str, destination: str, depart_date: str
    ) -> Optional[PriceRecord]:
        """
        Get the historical minimum price for a route.

        Args:
            origin: Origin airport code
            destination: Destination airport code
            depart_date: Departure date

        Returns:
            PriceRecord with minimum price, or None if no history
        """
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT MIN(price), currency, airline, checked_at, price_category
                FROM prices
                WHERE origin = ? AND destination = ? AND depart_date = ?
                """,
                (origin, destination, depart_date),
            ).fetchone()

        if row and row[0] is not None:
            return PriceRecord(
                price=row[0],
                currency=row[1],
                airline=row[2],
                checked_at=row[3],
                price_category=row[4] or "other",
            )
        return None

    def get_price_history(
        self, origin: str, destination: str, depart_date: str, limit: int = 20
    ) -> list[PriceRecord]:
        """
        Get recent price history for a route.

        Args:
            origin: Origin airport code
            destination: Destination airport code
            depart_date: Departure date
            limit: Maximum number of records to return

        Returns:
            List of PriceRecord objects, most recent first
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT price, currency, airline, checked_at, price_category
                FROM prices
                WHERE origin = ? AND destination = ? AND depart_date = ?
                ORDER BY checked_at DESC
                LIMIT ?
                """,
                (origin, destination, depart_date, limit),
            ).fetchall()

        return [
            PriceRecord(
                price=r[0],
                currency=r[1],
                airline=r[2],
                checked_at=r[3],
                price_category=r[4] or "other",
            )
            for r in rows
        ]
