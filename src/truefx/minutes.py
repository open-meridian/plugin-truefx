"""Each pair's one-minute bars of the mid, built from TrueFX's ticks for the
live dataset (item 95: recorded thinned, one row per pair per minute,
never every tick).

**A minute** runs from a whole minute since the epoch, UTC, to the next, by
TrueFX's own time on each tick. Its bar (`MinuteBar`) is the open, high, low
and close of the mid over the ticks the plugin heard in it, the last tick's
time and its raw record. Nothing trades on TrueFX, so its volume is 0, as a
day's is (days.py). A pair with no tick in a minute has no bar for it:
nothing is carried over from the minute before.

**A minute is closed** once TrueFX states a later minute's tick for the pair,
or once a poll asked after the minute's end has been answered. It is closed
once: a tick stated afterwards for a minute already closed is late, left out
of the bars (it is still a quote, a mid and part of the day).

**Only a minute heard whole is a bar.** Each poll answers each pair's latest
tick, so a pair's first tick heard is the latest at that poll: from then on
the plugin hears the pair's every poll, but not what came before it in that
minute. So the minute a pair's first tick falls in -- after the plugin
starts, and again after a poll that failed or a session TrueFX lost -- is
never a bar, and a minute a failed poll fell in is dropped. A bar is never
built across a restart or a lost session, so none is recorded twice, and
none is made up: the lake has no bar for such a minute. The book is held in
memory alone for that reason; a restart begins again.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from .pairs import BY_KEY, Pair
from .rates import Rate

NANOS_PER_SECOND = 1_000_000_000
MINUTE_NS = 60 * NANOS_PER_SECOND


def minute_of(at_ns: int) -> int:
    """The start of the minute an instant is in, in nanoseconds."""
    return at_ns - at_ns % MINUTE_NS


@dataclass(frozen=True)
class MinuteBar:
    """One pair's minute, built from its ticks; `whole` where the plugin
    heard the whole of it."""

    pair: str
    start_ns: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    last_ns: int
    ticks: int
    raw_key: str
    whole: bool

    @classmethod
    def first(cls, rate: Rate, whole: bool) -> MinuteBar:
        mid = rate.mid
        return cls(
            pair=rate.pair.key,
            start_ns=minute_of(rate.at_ns),
            open=mid,
            high=mid,
            low=mid,
            close=mid,
            last_ns=rate.at_ns,
            ticks=1,
            raw_key=rate.raw_key,
            whole=whole,
        )

    def with_tick(self, rate: Rate) -> MinuteBar:
        """The bar with one more tick, later than its last."""
        mid = rate.mid
        return replace(
            self,
            high=max(self.high, mid),
            low=min(self.low, mid),
            close=mid,
            last_ns=rate.at_ns,
            ticks=self.ticks + 1,
            raw_key=rate.raw_key,
        )

    @property
    def end_ns(self) -> int:
        return self.start_ns + MINUTE_NS

    @property
    def symbol(self) -> Pair:
        return BY_KEY[self.pair]


class MinuteBook:
    """Each pair's minute being built, the whole minutes closed since they
    were last taken, and each pair's latest whole minute."""

    def __init__(self) -> None:
        self.forming: dict[str, MinuteBar] = {}
        #: Each pair's latest tick heard, and the end of its last minute closed.
        self.heard_ns: dict[str, int] = {}
        self.closed_ns: dict[str, int] = {}
        #: The pairs heard since the plugin started or last lost a poll.
        self.running: set[str] = set()
        self.done: list[MinuteBar] = []
        self.latest: dict[str, MinuteBar] = {}
        #: Ticks stated for a minute already closed, left out.
        self.late = 0

    def add(self, rate: Rate) -> bool:
        """One tick into its pair's minute; False where it is no later than
        the pair's last (heard again), or late for a minute closed."""
        key = rate.pair.key
        if rate.at_ns <= self.heard_ns.get(key, -1):
            return False
        self.heard_ns[key] = rate.at_ns
        if minute_of(rate.at_ns) < self.closed_ns.get(key, 0):
            self.late += 1
            return False
        held = self.forming.get(key)
        if held is not None and held.start_ns == minute_of(rate.at_ns):
            self.forming[key] = held.with_tick(rate)
            return True
        if held is not None:
            self._close(held)
        self.forming[key] = MinuteBar.first(rate, whole=key in self.running)
        self.running.add(key)
        return True

    def lost(self) -> None:
        """A poll failed or TrueFX lost the session: each minute being built
        is dropped, and each pair's next tick heard begins again, its
        minute not a bar."""
        self.forming.clear()
        self.running.clear()

    def close(self, asked_ns: int) -> list[MinuteBar]:
        """The whole minutes closed since last taken, a poll asked at
        `asked_ns` answered: each minute ended by then closed too."""
        for key, bar in list(self.forming.items()):
            if bar.end_ns <= asked_ns:
                del self.forming[key]
                self._close(bar)
        done, self.done = self.done, []
        return sorted(done, key=lambda bar: (bar.start_ns, bar.pair))

    def _close(self, bar: MinuteBar) -> None:
        self.closed_ns[bar.pair] = max(self.closed_ns.get(bar.pair, 0), bar.end_ns)
        if bar.whole:
            self.done.append(bar)
            self.latest[bar.pair] = bar
