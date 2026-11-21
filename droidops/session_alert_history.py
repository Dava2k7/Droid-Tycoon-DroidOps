"""Ephemeral session-only Watch Droid alert history.

Deliberately performs NO file, settings, or external-storage operations.
History exists in RAM only and is discarded on application exit.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AlertEntry:
    timestamp: str
    droid: str
    classification: str


class SessionAlertHistory:
    def __init__(self):
        self._events = []

    def record(self, name: str, classification: str = "Confirmed", now=None) -> AlertEntry:
        if classification not in ("Confirmed", "Possible"):
            raise ValueError("Unrecognised alert classification")
        if not name or not name.strip():
            raise ValueError("An alert name is required")
        when = now if now is not None else datetime.now().astimezone()
        entry = AlertEntry(when.strftime("%d/%m/%Y %H:%M:%S"), name.strip(), classification)
        self._events.append(entry)
        return entry

    def entries(self):
        return tuple(self._events)

    def __len__(self):
        return len(self._events)

    def clear(self):
        self._events.clear()
