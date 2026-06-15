"""SQLite storage backend for price history."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..notifiers.base import FlightOffer, PriceRecord


@dataclass
class PriceStats:
    """Aggregated price statistics for a route."""
    record_count: int
    min_price: float
    avg_price: float
    previous_price: Optional[float]  # Price from the most recent prior check
    previous_checked_at: Optional[str]


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
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO prices (origin, destination, depart_date, return_date,
                    price, currency, airline, price_category, checked_at)
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
        cat = "LOW" if offer.price_category == "best" else "OTHER"
        print(f"[DB] Guardado: {offer.currency} {offer.price:,.0f} ({offer.airline}) [{cat}]")

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

    def get_price_stats(
        self, origin: str, destination: str, depart_date: str
    ) -> Optional[PriceStats]:
        """
        Get aggregated price statistics for a route.

        Returns None if no prior records exist.
        """
        with self._get_connection() as conn:
            # Aggregate stats
            row = conn.execute(
                """
                SELECT COUNT(*), MIN(price), AVG(price)
                FROM prices
                WHERE origin = ? AND destination = ? AND depart_date = ?
                """,
                (origin, destination, depart_date),
            ).fetchone()

            if row is None or row[0] == 0:
                return None

            count, min_price, avg_price = row

            # Most recent prior record
            prev = conn.execute(
                """
                SELECT price, checked_at
                FROM prices
                WHERE origin = ? AND destination = ? AND depart_date = ?
                ORDER BY checked_at DESC
                LIMIT 1
                """,
                (origin, destination, depart_date),
            ).fetchone()

        return PriceStats(
            record_count=count,
            min_price=min_price,
            avg_price=avg_price,
            previous_price=prev[0] if prev else None,
            previous_checked_at=prev[1] if prev else None,
        )
