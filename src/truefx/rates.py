"""TrueFX's rate responses, read once, at the edge, every figure exactly.

TrueFX's Market Data Web API Developer Guide (1.0v17, "HTTP Responses")
describes three formats; the plugin asks for two:

- **CSV** (`f=csv`), in an authenticated session: one group per pair,
  separated by white space, each `symbol,millis,bid big figure,bid points,
  offer big figure,offer points,high,low,open`. The bid is its big figure
  and its points as written one after the other (`1.16` and `431` is
  1.16431; `149.` and `512` is 149.512). High is the greatest offer since
  the pair's roll time, low the smallest bid, open the mid at the roll.
- **The default format**, the only one an unauthenticated session answers:
  one string, its fields in columns of fixed width, every pair's symbol
  first (7 characters each), then every bid big figure (4, padded in front
  with `#`), every bid's points (3, padded behind with `#`), every offer big
  figure (4), every offer's points (3), every high (7, padded in front),
  every low (7) and every timestamp (13, milliseconds since the epoch, UTC).
  It carries no open.

A figure is read from TrueFX's text as a `Decimal`, never through a float.
A group that does not read whole -- a pair the plugin does not list, a
figure that is not a number -- is returned as not read, with its text, and
never guessed. The words "not authorized" are TrueFX's answer to a session
it does not know (an expired one, or one on a server that failed over).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext

from .pairs import Pair, pair_of

#: TrueFX's answer to a session it does not know.
NOT_AUTHORIZED = "not authorized"
#: The default format's columns, in characters: symbol, bid big figure, bid
#: points, offer big figure, offer points, high, low, timestamp.
WIDTHS = (7, 4, 3, 4, 3, 7, 7, 13)
GROUP = sum(WIDTHS)
NANOS_PER_MILLI = 1_000_000

_NUMBER = re.compile(r"^\d+(\.\d*)?$")
_POINTS = re.compile(r"^\d+$")


@dataclass(frozen=True)
class Rate:
    """One pair's top of book, as TrueFX stated it."""

    pair: Pair
    at_ms: int
    bid: Decimal
    ask: Decimal
    #: The greatest offer and the smallest bid since the pair's roll time,
    #: and the mid at it (CSV only), as TrueFX states them.
    high: Decimal | None = None
    low: Decimal | None = None
    open: Decimal | None = None
    #: The raw record it was read from: `<file>#<line>`.
    raw_key: str = ""

    @property
    def at_ns(self) -> int:
        return self.at_ms * NANOS_PER_MILLI

    @property
    def mid(self) -> Decimal:
        """Halfway between the bid and the offer, exactly: a sum of two
        decimals halved always terminates."""
        with localcontext() as exact:
            exact.prec = 60
            return (self.bid + self.ask) / 2


@dataclass(frozen=True)
class Read:
    """What one response said: its rates, and each group that did not read."""

    rates: tuple[Rate, ...]
    unread: tuple[str, ...] = ()


def _figure(text: str) -> Decimal | None:
    cleaned = text.strip().strip("#")
    if not _NUMBER.match(cleaned):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _price(big: str, points: str) -> Decimal | None:
    """A price from its big figure and its points, written one after the
    other: `1.16` `431` -> 1.16431, `149.` `512` -> 149.512."""
    big, points = big.strip().strip("#"), points.strip().strip("#")
    if not _NUMBER.match(big) or not _POINTS.match(points):
        return None
    return _figure(big + points)


def _millis(text: str) -> int | None:
    cleaned = text.strip()
    return int(cleaned) if cleaned.isdigit() else None


def _rate(
    symbol: str,
    millis: str,
    bid: tuple[str, str],
    ask: tuple[str, str],
    high: str,
    low: str,
    open_: str | None,
    raw_key: str,
) -> Rate | None:
    pair = pair_of(symbol)
    at = _millis(millis)
    bid_price, ask_price = _price(*bid), _price(*ask)
    if pair is None or at is None or bid_price is None or ask_price is None:
        return None
    return Rate(
        pair=pair,
        at_ms=at,
        bid=bid_price,
        ask=ask_price,
        high=_figure(high),
        low=_figure(low),
        open=None if open_ is None else _figure(open_),
        raw_key=raw_key,
    )


def read_csv(body: str, raw_key: str = "") -> Read:
    """A CSV rate response: each pair's group, separated by white space."""
    rates: list[Rate] = []
    unread: list[str] = []
    for group in body.split():
        fields = group.split(",")
        rate = None
        if len(fields) == 9:
            symbol, millis, bid_big, bid_points, ask_big, ask_points, high, low, open_ = fields
            rate = _rate(symbol, millis, (bid_big, bid_points), (ask_big, ask_points),
                         high, low, open_, raw_key)  # fmt: skip
        if rate is None:
            unread.append(group[:200])
        else:
            rates.append(rate)
    return Read(tuple(rates), tuple(unread))


def read_default(body: str, raw_key: str = "") -> Read:
    """A default-format response: fixed-width columns, every pair's field
    of each column in turn. A body whose length is not a whole number of
    pairs is not read at all."""
    text = "".join(body.split())
    if not text:
        return Read(())
    if len(text) % GROUP:
        return Read((), (text[:200],))
    count = len(text) // GROUP
    columns: list[list[str]] = []
    at = 0
    for width in WIDTHS:
        columns.append([text[at + i * width : at + (i + 1) * width] for i in range(count)])
        at += width * count
    rates: list[Rate] = []
    unread: list[str] = []
    for i in range(count):
        symbol, bid_big, bid_points, ask_big, ask_points, high, low, millis = (
            column[i] for column in columns
        )
        rate = _rate(symbol, millis, (bid_big, bid_points), (ask_big, ask_points),
                     high, low, None, raw_key)  # fmt: skip
        if rate is None:
            unread.append("".join(column[i] for column in columns))
        else:
            rates.append(rate)
    return Read(tuple(rates), tuple(unread))


def is_session_id(body: str, username: str, qualifier: str) -> bool:
    """Whether `body` is the session ID TrueFX answers a session request
    with: `username:password:qualifier:digits`, for this username and
    qualifier."""
    parts = body.strip().split(":")
    return (
        len(parts) == 4
        and parts[0] == username
        and parts[2] == qualifier
        and parts[3].isalnum()
        and bool(parts[3])
    )
