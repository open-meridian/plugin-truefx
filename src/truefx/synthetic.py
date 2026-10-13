"""Sample data: TrueFX's answers from files, never from TrueFX.

A developer's setting (`sample_data`, shown only on a development
deployment) turns it on. The client asks exactly as it asks TrueFX, keeps
each answer as a raw record and reads it the same way; only the transport
differs. The synthetic feed this package carries has invented values in
TrueFX's layouts, and is what the tests, CI and `make e2e` replay:

- `synthetic/rates.csv`: TrueFX's polls in turn, a step each, every rate
  `step,symbol,millis,bid,ask,high,low,open`, on business date 9 October
  2026. `Synthetic` answers them as TrueFX's API does: the address with no
  query a default-format snapshot of the ten unauthenticated pairs, as they
  stand after the next step; a session request its ID; each poll of the
  session the next step's rates in CSV, then nothing once every step has
  been answered, as an incremental session answers while nothing moves. It
  checks no username: any is a session.
- `synthetic/history/`: three of TrueFX's monthly tick files for October
  2026 (EUR/USD, USD/JPY and GBP/USD), business dates 2 to 8 October, which
  the plugin reads as it reads the files a person puts in its storage
  (history.py). With sample data on they are copied under the storage's
  `synthetic/history/`, so a row's raw record is found there.
"""

from __future__ import annotations

import shutil
import urllib.parse
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from .client import Response
from .pairs import UNAUTHENTICATED
from .rates import WIDTHS

#: Where sample data's history files go, under the plugin's storage.
HISTORY = "synthetic/history"


@dataclass(frozen=True)
class Stated:
    symbol: str
    millis: str
    bid: str
    ask: str
    high: str
    low: str
    open: str


def steps() -> list[list[Stated]]:
    """The synthetic feed's polls, in turn."""
    text = (resources.files("truefx") / "synthetic" / "rates.csv").read_text(encoding="utf-8")
    by_step: dict[int, list[Stated]] = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        step, *fields = line.split(",")
        by_step.setdefault(int(step), []).append(Stated(*fields))
    return [by_step[step] for step in sorted(by_step)]


def _split(price: str) -> tuple[str, str]:
    """A price as its big figure and its points: TrueFX's last three digits
    are the points."""
    return price[:-3], price[-3:]


def csv_group(rate: Stated) -> str:
    bid_big, bid_points = _split(rate.bid)
    ask_big, ask_points = _split(rate.ask)
    return ",".join(
        (rate.symbol, rate.millis, bid_big, bid_points, ask_big, ask_points,
         rate.high, rate.low, rate.open)
    )  # fmt: skip


def default_body(rates: list[Stated]) -> str:
    """Rates in the default format: fixed-width columns, each pair's field
    of each column in turn, padded with `#` as TrueFX pads them."""
    columns: list[list[str]] = [[] for _ in WIDTHS]
    for rate in rates:
        bid_big, bid_points = _split(rate.bid)
        ask_big, ask_points = _split(rate.ask)
        fields = (rate.symbol, bid_big, bid_points, ask_big, ask_points, rate.high, rate.low,
                  rate.millis)  # fmt: skip
        for i, (text, width) in enumerate(zip(fields, WIDTHS, strict=True)):
            padded = text.ljust(width, "#") if i in (2, 4) else text.rjust(width, "#")
            columns[i].append(padded[:width])
    return "".join("".join(column) for column in columns)


@dataclass
class Synthetic:
    """TrueFX's API, answered from the synthetic feed."""

    feed: list[list[Stated]] = field(default_factory=steps)
    at: int = 0
    latest: dict[str, Stated] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)

    def _next(self) -> list[Stated]:
        if self.at >= len(self.feed):
            return []
        moved = self.feed[self.at]
        self.at += 1
        for rate in moved:
            self.latest[rate.symbol] = rate
        return moved

    def __call__(self, url: str) -> Response:
        split = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(split.query))
        self.asked.append("session" if "u" in query else "poll" if "id" in query else "snapshot")
        if "u" in query and "q" in query:
            return Response(200, f"{query['u']}:string:{query['q']}:1791547200000")
        if "id" in query:
            moved = self._next()
            if query.get("s") == "y":
                moved = list(self.latest.values())
            return Response(200, "\n".join(csv_group(rate) for rate in moved))
        self._next()
        served = [self.latest[p.symbol] for p in UNAUTHENTICATED if p.symbol in self.latest]
        return Response(200, default_body(served))


def copy_history(root: Path) -> Path:
    """Sample data's history files, copied under the storage; where."""
    folder = root / HISTORY
    folder.mkdir(parents=True, exist_ok=True)
    source = resources.files("truefx") / "synthetic" / "history"
    for entry in source.iterdir():
        if entry.name.endswith(".csv"):
            target = folder / entry.name
            if not target.exists():
                with resources.as_file(entry) as path:
                    shutil.copyfile(path, target)
    return folder
