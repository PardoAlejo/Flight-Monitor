"""Persistent scheduler helpers for hourly retry execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScheduledSlot:
    """Represents one scheduled run window for a given day."""

    slot_id: str
    scheduled_for: datetime


class RetryScheduler:
    """Track scheduled runs and retry failed or missed ones one hour later."""

    def __init__(self, state_path: str, scheduled_times: list[str], retry_delay_minutes: int = 60):
        self.state_path = Path(state_path)
        self.retry_delay = timedelta(minutes=retry_delay_minutes)
        self.scheduled_times = self._parse_scheduled_times(scheduled_times)

    def next_due_slot(self, now: datetime) -> ScheduledSlot | None:
        """Return the next scheduled slot that should be attempted now."""
        if not self.scheduled_times:
            return None

        state = self._load_state()
        for hour, minute in self.scheduled_times:
            scheduled_for = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if scheduled_for > now:
                continue

            slot_id = scheduled_for.strftime("%Y-%m-%dT%H:%M")
            slot_state = state.get(slot_id, {})

            if slot_state.get("completed_at"):
                continue

            last_attempt_at = self._parse_datetime(slot_state.get("last_attempt_at"))
            if last_attempt_at and now - last_attempt_at < self.retry_delay:
                continue

            return ScheduledSlot(slot_id=slot_id, scheduled_for=scheduled_for)

        return None

    def mark_attempt(self, slot: ScheduledSlot, attempted_at: datetime, succeeded: bool) -> None:
        """Persist the outcome for a scheduled attempt."""
        state = self._load_state()
        slot_state = state.get(slot.slot_id, {})
        slot_state["scheduled_for"] = slot.scheduled_for.isoformat(timespec="minutes")
        slot_state["last_attempt_at"] = attempted_at.isoformat(timespec="seconds")
        slot_state["last_status"] = "success" if succeeded else "failed"
        if succeeded:
            slot_state["completed_at"] = attempted_at.isoformat(timespec="seconds")
        else:
            slot_state.pop("completed_at", None)
        state[slot.slot_id] = slot_state
        self._save_state(self._prune_old_slots(state, attempted_at))

    def _load_state(self) -> dict[str, dict[str, Any]]:
        if not self.state_path.exists():
            return {}

        try:
            raw = json.loads(self.state_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

        if not isinstance(raw, dict):
            return {}

        return {str(key): value for key, value in raw.items() if isinstance(value, dict)}

    def _save_state(self, state: dict[str, dict[str, Any]]) -> None:
        self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

    def _prune_old_slots(
        self, state: dict[str, dict[str, Any]], now: datetime
    ) -> dict[str, dict[str, Any]]:
        keep_after = now.date() - timedelta(days=2)
        pruned: dict[str, dict[str, Any]] = {}

        for slot_id, slot_state in state.items():
            slot_dt = self._parse_datetime(slot_state.get("scheduled_for"))
            if slot_dt is None:
                slot_dt = self._parse_slot_id(slot_id)
            if slot_dt and slot_dt.date() >= keep_after:
                pruned[slot_id] = slot_state

        return pruned

    def _parse_scheduled_times(self, scheduled_times: list[str]) -> list[tuple[int, int]]:
        parsed: list[tuple[int, int]] = []
        for value in scheduled_times:
            try:
                hour_str, minute_str = value.split(":", maxsplit=1)
                hour = int(hour_str)
                minute = int(minute_str)
            except ValueError:
                print(f"[Scheduler] Hora invalida ignorada: {value}")
                continue

            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                print(f"[Scheduler] Hora fuera de rango ignorada: {value}")
                continue

            parsed.append((hour, minute))

        return sorted(set(parsed))

    def _parse_slot_id(self, slot_id: str) -> datetime | None:
        return self._parse_datetime(slot_id)

    def _parse_datetime(self, value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None

        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
