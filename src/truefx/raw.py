"""TrueFX's raw responses, kept as the plugin's raw records (decisions/028).

Every rate response TrueFX sends -- "not authorized" and an error as much as
a rate -- is kept before anything is read from it, exactly as it arrived,
with the request that asked for it and when it was received. A row
converted from it names it by a `RawRecordRef` whose key is the record's
path in the plugin's storage, then `#` and its line
(`responses/2026-10-09/rates-14.jsonl#41`), so a person auditing a row
follows it here and finds what TrueFX said.

Nothing kept names the TrueFX username: a session's requests are kept as
`connect.html?id=<session>`, and the answer to a session request, which is
the session ID and so carries the username, is kept as `<session id>`.

The plugin declares one kind of raw record, `responses` (declaration.py),
kept in units of a UTC day: `responses/2026-10-09/`, its responses a line
each of one file per hour, a line added only when TrueFX's answer changed
(an incremental session answers nothing while nothing moves).

Past the kind's window a day's unit is archived, kept or deleted as its
`responses_past_window` setting says, through the SDK (`tend`), which
reports each move before anything is removed; and what storage holds is said
on every heartbeat (`plugin.stored`).

Where the records live: `meridian.edge.storage_dir()` where the deployment
grants the instance storage (a data plugin is an edge role); otherwise a
temporary directory, which a restart loses.
"""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import meridian
from meridian import edge
from meridian.v1 import sidecar_pb2

log = logging.getLogger(__name__)

KIND = "responses"
LABEL = "Raw responses"
#: The kind's default window: a week of TrueFX's answers, polled as often as
#: once a second, enough to re-convert a row a person questions. An admin
#: sets it in Settings.
WINDOW_DAYS = 7
NANOS_PER_SECOND = 1_000_000_000


def storage_root() -> Path:
    """The instance's granted storage, else a temporary directory."""
    granted = edge.storage_dir()
    if granted is not None:
        return granted
    return Path(tempfile.mkdtemp(prefix="meridian-truefx-"))


def _utc(received_ns: int) -> datetime:
    return datetime.fromtimestamp(received_ns // NANOS_PER_SECOND, tz=UTC)


@dataclass(frozen=True)
class Unit:
    """One UTC day's responses: its path in storage, how many records it
    holds and when the first and last arrived."""

    unit: str
    day: date
    records: int
    first_ns: int
    last_ns: int


class RawStore:
    """Raw records as lines of files under the storage's `responses/`, one
    unit a day, one file an hour."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._last: dict[str, tuple[str, str]] = {}
        self._lines: dict[str, int] = {}

    def keep(self, call: str, record: dict[str, Any]) -> str:
        """Keep one response as the next line of its hour's file for `call`,
        unless its body is the one kept last there, which the returned key
        then names again: `<file>#<line>`."""
        received = _utc(int(record["received_at_ns"]))
        key = f"{KIND}/{received.date().isoformat()}/{call}-{received.hour:02d}.jsonl"
        body = str(record.get("body", ""))
        held = self._last.get(key)
        if held is not None and held[0] == body:
            return held[1]
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = self._lines.get(key)
        if lines is None:
            lines = sum(1 for _ in path.open(encoding="utf-8")) if path.exists() else 0
        with path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(record, sort_keys=True) + "\n")
        self._lines[key] = lines + 1
        named = f"{key}#{lines}"
        self._last[key] = (body, named)
        return named

    def get(self, ref_key: str) -> dict[str, Any] | None:
        """The record a row's reference names; None once it has moved."""
        key, _, where = ref_key.partition("#")
        path = self.root / key
        if not path.is_file() or not where.isdigit():
            return None
        lines = path.read_text(encoding="utf-8").splitlines()
        if int(where) >= len(lines):
            return None
        line: dict[str, Any] = json.loads(lines[int(where)])
        return line

    def units(self) -> list[Unit]:
        """Each day's unit in storage, oldest first."""
        base = self.root / KIND
        found: list[Unit] = []
        if not base.is_dir():
            return found
        for directory in sorted(p for p in base.iterdir() if p.is_dir()):
            try:
                day = date.fromisoformat(directory.name)
            except ValueError:
                continue
            stamps = [
                int(json.loads(line)["received_at_ns"])
                for path in sorted(directory.glob("*.jsonl"))
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if stamps:
                found.append(Unit(f"{KIND}/{directory.name}", day, len(stamps),
                                  min(stamps), max(stamps)))  # fmt: skip
        return found


async def tend(
    plugin: meridian.Plugin, store: RawStore, window_days: int, past: str, today: date
) -> None:
    """Move each day's unit past the window as `past` says -- `archived` or
    `deleted` through the SDK, `kept` left -- never today's, which is still
    being written; then say what storage holds. A move refused keeps the
    unit, and the next pass tries again."""
    cutoff = today - timedelta(days=max(window_days, 0))
    for unit in store.units():
        if unit.day >= cutoff or unit.day >= today or past == "kept":
            continue
        try:
            if past == "archived":
                await plugin.archive_unit(
                    KIND,
                    unit.unit,
                    record_count=unit.records,
                    first_received_ns=unit.first_ns,
                    last_received_ns=unit.last_ns,
                )
            elif past == "deleted":
                await plugin.delete_unit(
                    KIND,
                    unit.unit,
                    record_count=unit.records,
                    first_received_ns=unit.first_ns,
                    last_received_ns=unit.last_ns,
                )
        except (meridian.MeridianError, ValueError, RuntimeError, OSError) as refused:
            log.warning("%s kept, its move refused: %s", unit.unit, refused)
    held = store.units()
    if held:
        plugin.stored = [
            sidecar_pb2.StoredSpan(
                record_kind=KIND,
                record_count=sum(u.records for u in held),
                first_received_ns=min(u.first_ns for u in held),
                last_received_ns=max(u.last_ns for u in held),
            )
        ]
