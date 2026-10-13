"""The FX day, and each pair's daily bar built from TrueFX's ticks.

**The day** (reference/fx-and-crypto-identifiers.md: "The FX trading day
rolls at 17:00 America/New_York"; the calendars spec's Q7, the cut "17:00
America/New_York for FX"): the daily dataset declares New York's day ending
at 17:00 (`day_time_zone` America/New_York, `day_end_minute` 1020). A
business date D runs from 17:00 New York on the day before D to 17:00 on D,
so a tick at 17:05 on a Sunday is Monday's, and a Friday's last tick before
17:00 closes Friday. New York's clocks change; the day is always 17:00 to
17:00 local, so it is 23 or 25 hours long across a change.

**A day's bar** (`DayBar`) is built from the ticks the plugin saw, each one
a top of book: open, high, low and close of the mid, and the closing bid and
offer, with the first and last tick's times and the raw record of the last.
TrueFX's rates are indicative, not executable, and nothing trades on TrueFX,
so a bar's volume is 0, which the dictionary reads as "nothing traded". Its
close is the dataset's declared close: the last mid of the day.

Ticks polled from TrueFX's API are what the plugin saw once a second; ticks
read from TrueFX's history files are every tick it recorded (history.py).
Where both hold a day, the files' bar is the day's (work.py).

The book of days being built is kept in the plugin's storage, a file per
business date (`days/2026-10-09.json`), so a restart carries on the day it
was building; the ticks it missed while stopped are missing from the bar.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from .pairs import BY_KEY, Pair
from .rates import Rate

log = logging.getLogger(__name__)

DAY_TIME_ZONE = "America/New_York"
#: 17:00, in minutes after midnight.
DAY_END_MINUTE = 17 * 60
NEW_YORK = ZoneInfo(DAY_TIME_ZONE)
NANOS_PER_SECOND = 1_000_000_000
_CUT = time(DAY_END_MINUTE // 60, DAY_END_MINUTE % 60)


def _ns(moment: datetime) -> int:
    return int(moment.timestamp()) * NANOS_PER_SECOND + moment.microsecond * 1_000


def business_date(at_ns: int) -> date:
    """The business date an instant is in: its New York date, or the next
    one from 17:00."""
    local = datetime.fromtimestamp(at_ns // NANOS_PER_SECOND, tz=NEW_YORK)
    return local.date() + timedelta(days=1) if local.time() >= _CUT else local.date()


def day_bounds(day: date) -> tuple[int, int]:
    """Business date `day`, from 17:00 New York the day before to 17:00 on
    it, in nanoseconds since the epoch."""
    end = datetime.combine(day, _CUT, NEW_YORK)
    start = datetime.combine(day - timedelta(days=1), _CUT, NEW_YORK)
    return _ns(start), _ns(end)


@dataclass(frozen=True)
class DayBar:
    """One pair's day, built from its ticks."""

    pair: str
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    bid: Decimal
    ask: Decimal
    first_ns: int
    last_ns: int
    ticks: int
    raw_key: str

    @classmethod
    def first(cls, rate: Rate) -> DayBar:
        mid = rate.mid
        return cls(
            pair=rate.pair.key,
            day=business_date(rate.at_ns),
            open=mid,
            high=mid,
            low=mid,
            close=mid,
            bid=rate.bid,
            ask=rate.ask,
            first_ns=rate.at_ns,
            last_ns=rate.at_ns,
            ticks=1,
            raw_key=rate.raw_key,
        )

    def with_tick(self, rate: Rate) -> DayBar:
        """The bar with one more tick, which is no earlier than its last."""
        mid = rate.mid
        return replace(
            self,
            high=max(self.high, mid),
            low=min(self.low, mid),
            close=mid,
            bid=rate.bid,
            ask=rate.ask,
            last_ns=rate.at_ns,
            ticks=self.ticks + 1,
            raw_key=rate.raw_key,
        )

    def merged(self, later: DayBar) -> DayBar:
        """This bar and one built from the day's later ticks, as one: a day
        whose ticks are split over two of TrueFX's monthly files."""
        first, last = (self, later) if self.first_ns <= later.first_ns else (later, self)
        return replace(
            first,
            high=max(first.high, last.high),
            low=min(first.low, last.low),
            close=last.close,
            bid=last.bid,
            ask=last.ask,
            last_ns=max(first.last_ns, last.last_ns),
            ticks=first.ticks + last.ticks,
            raw_key=last.raw_key,
        )

    @property
    def symbol(self) -> Pair:
        return BY_KEY[self.pair]

    def as_json(self) -> dict[str, object]:
        held = asdict(self)
        held["day"] = self.day.isoformat()
        for name in ("open", "high", "low", "close", "bid", "ask"):
            held[name] = str(held[name])
        return held

    @classmethod
    def from_json(cls, held: dict[str, object]) -> DayBar:
        return cls(
            pair=str(held["pair"]),
            day=date.fromisoformat(str(held["day"])),
            open=Decimal(str(held["open"])),
            high=Decimal(str(held["high"])),
            low=Decimal(str(held["low"])),
            close=Decimal(str(held["close"])),
            bid=Decimal(str(held["bid"])),
            ask=Decimal(str(held["ask"])),
            first_ns=int(str(held["first_ns"])),
            last_ns=int(str(held["last_ns"])),
            ticks=int(str(held["ticks"])),
            raw_key=str(held["raw_key"]),
        )


class DayBook:
    """Each pair's days being built from ticks, by business date; kept in
    `<root>/days/` when given a root."""

    #: Days held in memory; older ones are read back from storage.
    HELD_DAYS = 10

    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self.days: dict[date, dict[str, DayBar]] = {}
        self._changed: set[date] = set()

    def _path(self, day: date) -> Path | None:
        return None if self.root is None else self.root / "days" / f"{day.isoformat()}.json"

    def _load(self, day: date) -> dict[str, DayBar]:
        held = self.days.get(day)
        if held is not None:
            return held
        loaded: dict[str, DayBar] = {}
        path = self._path(day)
        if path is not None and path.is_file():
            try:
                for kept in json.loads(path.read_text(encoding="utf-8")):
                    bar = DayBar.from_json(kept)
                    loaded[bar.pair] = bar
            except (OSError, ValueError, KeyError) as unreadable:
                log.warning("%s was not read: %s", path, unreadable)
        self.days[day] = loaded
        return loaded

    def add(self, rate: Rate) -> bool:
        """One tick into its pair's day; False where it is no later than the
        day's last tick (heard again, or out of order), which changes
        nothing."""
        day = business_date(rate.at_ns)
        bars = self._load(day)
        held = bars.get(rate.pair.key)
        if held is None:
            bars[rate.pair.key] = DayBar.first(rate)
        elif rate.at_ns <= held.last_ns:
            return False
        else:
            bars[rate.pair.key] = held.with_tick(rate)
        self._changed.add(day)
        return True

    def get(self, pair: Pair, day: date) -> DayBar | None:
        return self._load(day).get(pair.key)

    def held_days(self) -> list[date]:
        """Every business date the book holds, in memory or in storage."""
        found = set(self.days)
        if self.root is not None and (self.root / "days").is_dir():
            for path in (self.root / "days").glob("*.json"):
                try:
                    found.add(date.fromisoformat(path.stem))
                except ValueError:
                    continue
        return sorted(found)

    def bars(self, days: Iterable[date]) -> Iterator[DayBar]:
        for day in days:
            yield from self._load(day).values()

    def save(self) -> None:
        """Write each day changed since the last save, and let go of days
        older than the ones held in memory."""
        for day in sorted(self._changed):
            path = self._path(day)
            if path is None:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            kept = [bar.as_json() for bar in sorted(self.days[day].values(), key=lambda b: b.pair)]
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(kept, indent=1), encoding="utf-8")
            temporary.replace(path)
        self._changed.clear()
        if self.root is not None:
            for day in sorted(self.days)[: -self.HELD_DAYS]:
                del self.days[day]
