"""Storage backends for price history."""

from .sqlite import SQLiteStorage

__all__ = ["SQLiteStorage"]
