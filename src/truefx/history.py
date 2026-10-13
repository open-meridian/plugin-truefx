"""Daily bars from TrueFX's historical tick files.

TrueFX publishes its history as files to download, one a pair a month, from
its website's Historical Downloads page, free with a TrueFX account: "Please
log in or register for free access to the historical data downloads". There
is no API for them; the Market Data Web API serves only the current top of
book. So the plugin does not download them: a person with a TrueFX account
downloads the months wanted and puts them in the plugin's storage under
`history/` (README, "History"), and the plugin reads whatever is there. It
holds no website password.

**A file** is one pair's month, as TrueFX publishes it -- a `.csv`, or the
`.zip` holding one -- each line a tick: the pair, the time in GMT to the
millisecond, the bid and the offer (`EUR/USD,20261001 21:00:00.123,1.17012,
1.17015`). A line that does not read is counted, never guessed. Every tick
goes into its pair's day (days.py: New York's, ending at 17:00), so a day
built from the files holds every tick TrueFX recorded, not one a second.

**What the files cover**: a business date is covered where every month its
hours touch is held for the pair -- business date 1 October starts at 17:00
New York on 30 September, in September's file -- so a day half in a month
not held is not served from the files.

Reading a month is slow (a few million lines), so each file's days are read
once and kept beside it, under `history-days/`, until the file changes.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .days import DayBar, DayBook, day_bounds
from .pairs import Pair, pair_of
from .rates import NANOS_PER_MILLI, Rate

log = logging.getLogger(__name__)

#: The directory under storage a person puts TrueFX's files in.
FOLDER = "history"
_SUFFIXES = (".csv", ".zip")


def _instant_ms(text: str) -> int | None:
    """`20261001 21:00:00.123`, GMT, as milliseconds since the epoch."""
    try:
        moment = datetime.strptime(text.strip(), "%Y%m%d %H:%M:%S.%f").replace(tzinfo=UTC)
    except ValueError:
        return None
    return int(moment.timestamp()) * 1000 + moment.microsecond // 1000


def _decimal(text: str) -> Decimal | None:
    try:
        value = Decimal(text.strip())
    except InvalidOperation:
        return None
    return value if value.is_finite() and value > 0 else None


def _lines(path: Path) -> Iterator[str]:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".csv"):
                    with archive.open(name) as member:
                        yield from io.TextIOWrapper(member, encoding="utf-8", errors="replace")
                    return
        return
    with path.open(encoding="utf-8", errors="replace") as text:
        yield from text


@dataclass(frozen=True)
class Month:
    """One file's days: its pair, the month its ticks are in, its days'
    bars, and the lines that did not read."""

    name: str
    pair: str
    month: tuple[int, int]
    bars: tuple[DayBar, ...]
    unread: int

    def as_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "pair": self.pair,
            "month": list(self.month),
            "bars": [bar.as_json() for bar in self.bars],
            "unread": self.unread,
        }

    @classmethod
    def from_json(cls, held: dict[str, object]) -> Month:
        month = held["month"]
        assert isinstance(month, list)
        bars = held["bars"]
        assert isinstance(bars, list)
        return cls(
            name=str(held["name"]),
            pair=str(held["pair"]),
            month=(int(month[0]), int(month[1])),
            bars=tuple(DayBar.from_json(bar) for bar in bars),
            unread=int(str(held["unread"])),
        )


def read_month(path: Path, raw_prefix: str) -> Month | None:
    """A file's days, every tick in its pair's day; None where no line names
    a pair the plugin lists."""
    book = DayBook()
    pair: Pair | None = None
    month: tuple[int, int] | None = None
    unread = 0
    for number, line in enumerate(_lines(path)):
        fields = line.strip().split(",")
        if len(fields) != 4:
            unread += 1 if line.strip() else 0
            continue
        named, at = pair_of(fields[0]), _instant_ms(fields[1])
        bid, ask = _decimal(fields[2]), _decimal(fields[3])
        if named is None or at is None or bid is None or ask is None or (pair and named != pair):
            unread += 1
            continue
        if pair is None:
            pair = named
            moment = datetime.fromtimestamp(at // 1000, tz=UTC)
            month = (moment.year, moment.month)
        book.add(Rate(named, at, bid, ask, raw_key=f"{raw_prefix}{path.name}#{number}"))
    if pair is None or month is None:
        return None
    bars = tuple(sorted(book.bars(book.held_days()), key=lambda b: b.day))
    return Month(path.name, pair.key, month, bars, unread)


@dataclass
class History:
    """The files under a directory, read into days: what they cover, and
    each pair's day built from them."""

    folder: Path
    #: How a raw record in these files is named: their path under storage.
    raw_prefix: str = f"{FOLDER}/"
    cache: Path | None = None
    months: dict[str, Month] = field(default_factory=dict)
    _seen: dict[str, tuple[int, int]] = field(default_factory=dict)

    def files(self) -> list[Path]:
        if not self.folder.is_dir():
            return []
        return sorted(p for p in self.folder.iterdir() if p.suffix.lower() in _SUFFIXES)

    def refresh(self) -> None:
        """Read each file new or changed since last read, from its kept days
        where they are still the file's; forget files that went."""
        present = {path.name: path for path in self.files()}
        for gone in set(self.months) - set(present):
            del self.months[gone]
            self._seen.pop(gone, None)
        for name, path in present.items():
            stat = path.stat()
            stamp = (stat.st_size, stat.st_mtime_ns)
            if self._seen.get(name) == stamp:
                continue
            month = self._kept(name, stamp)
            if month is None:
                month = read_month(path, self.raw_prefix)
                self._keep(name, stamp, month)
            self._seen[name] = stamp
            if month is None:
                log.warning("%s names no pair this plugin lists; not read", name)
                self.months.pop(name, None)
            else:
                self.months[name] = month

    def _kept_path(self, name: str) -> Path | None:
        return None if self.cache is None else self.cache / f"{name}.json"

    def _kept(self, name: str, stamp: tuple[int, int]) -> Month | None:
        path = self._kept_path(name)
        if path is None or not path.is_file():
            return None
        try:
            held = json.loads(path.read_text(encoding="utf-8"))
            if tuple(held.get("stamp", ())) != stamp:
                return None
            return Month.from_json(held["month"])
        except (OSError, ValueError, KeyError, AssertionError):
            return None

    def _keep(self, name: str, stamp: tuple[int, int], month: Month | None) -> None:
        path = self._kept_path(name)
        if path is None or month is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"stamp": list(stamp), "month": month.as_json()}),
                        encoding="utf-8")  # fmt: skip

    def held(self, pair: Pair) -> set[tuple[int, int]]:
        return {m.month for m in self.months.values() if m.pair == pair.key}

    def covers(self, pair: Pair, day: date) -> bool:
        """Whether the files hold every month business date `day` touches."""
        start, end = day_bounds(day)
        held = self.held(pair)
        if not held:
            return False
        first = datetime.fromtimestamp(start // 1_000_000_000, tz=UTC)
        last = datetime.fromtimestamp((end - NANOS_PER_MILLI) // 1_000_000_000, tz=UTC)
        return (first.year, first.month) in held and (last.year, last.month) in held

    def bar(self, pair: Pair, day: date) -> DayBar | None:
        """The pair's day from the files, where they cover it and it has ticks."""
        if not self.covers(pair, day):
            return None
        found: DayBar | None = None
        for month in self.months.values():
            if month.pair != pair.key:
                continue
            for bar in month.bars:
                if bar.day == day:
                    found = bar if found is None else found.merged(bar)
        return found

    def first_day(self, pair: Pair) -> date | None:
        """The first business date the files cover for the pair."""
        days = [
            bar.day
            for month in self.months.values()
            if month.pair == pair.key
            for bar in month.bars
            if self.covers(pair, bar.day)
        ]
        return min(days) if days else None

    def unread(self) -> int:
        return sum(month.unread for month in self.months.values())
