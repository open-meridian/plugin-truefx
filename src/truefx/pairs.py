"""TrueFX's pairs, and the plugin's pair map: each pair as two cash
instruments, resolved through the master.

A pair is not an instrument (plans/the-lake-prices-the-book; ruled
2026-10-13, the spot-FX plugin's Q6: no pair record). TrueFX names a pair by
two ISO 4217 codes, base first (`EUR/USD`), and quotes the base currency's
price in the quote currency: EUR/USD 1.16431 is what one euro costs in
dollars, so that rate is the price of the euro's cash instrument, in dollars;
USD/JPY 149.512 is the dollar's, in yen. Nothing is inverted or crossed
(spec/the-lake, Q3): a pair TrueFX does not quote is not made from two it
does.

**The pairs** are the ones TrueFX's Market Data Web API Developer Guide lists
(1.0v17, sections 1.1.1 and 1.1.2): ten to an unauthenticated session, and
those ten and seventeen more to an authenticated one. The list is the
plugin's own, not the deployment's: no vendor code is a key in core.

**The pair map** (`PairMap`) keeps, in the plugin's storage, the
deployment's cash instrument each currency code resolved to (W3.1, by its
`iso4217` identifier), the codes that did not resolve with why, and each
subject the lake asked for that the plugin named by reading its record
(W3.6). A row names the base currency's instrument as its subject and its
price as a `Money` in the quote currency's code, which core resolves to that
currency's cash instrument; a pair whose base or quote did not resolve is
left out, never guessed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Pair:
    """One TrueFX pair: its symbol as TrueFX writes it, and its two codes."""

    symbol: str

    @property
    def base(self) -> str:
        return self.symbol[:3]

    @property
    def quote(self) -> str:
        return self.symbol[4:]

    @property
    def key(self) -> str:
        """The pair in a row key or a file name: `EURUSD`."""
        return self.base + self.quote


def _pairs(*symbols: str) -> tuple[Pair, ...]:
    return tuple(Pair(symbol) for symbol in symbols)


#: The ten pairs an unauthenticated session serves, in the guide's order.
UNAUTHENTICATED = _pairs(
    "EUR/USD", "USD/JPY", "GBP/USD", "EUR/GBP", "USD/CHF",
    "EUR/JPY", "EUR/CHF", "USD/CAD", "AUD/USD", "GBP/JPY",
)  # fmt: skip
#: The twenty-seven an authenticated session serves: those ten first.
AUTHENTICATED = UNAUTHENTICATED + _pairs(
    "AUD/CAD", "AUD/CHF", "AUD/JPY", "AUD/NZD", "CAD/CHF", "CAD/JPY",
    "CHF/JPY", "EUR/AUD", "EUR/CAD", "EUR/NOK", "EUR/NZD", "GBP/CAD",
    "GBP/CHF", "NZD/JPY", "NZD/USD", "USD/NOK", "USD/SEK",
)  # fmt: skip
BY_SYMBOL = {pair.symbol: pair for pair in AUTHENTICATED}
BY_KEY = {pair.key: pair for pair in AUTHENTICATED}


def served(authenticated: bool) -> tuple[Pair, ...]:
    """The pairs a session of that kind serves."""
    return AUTHENTICATED if authenticated else UNAUTHENTICATED


def currencies(pairs: tuple[Pair, ...]) -> tuple[str, ...]:
    """Every ISO code `pairs` name, once each, in their order."""
    found: dict[str, None] = {}
    for pair in pairs:
        found[pair.base] = None
        found[pair.quote] = None
    return tuple(found)


def pair_of(text: str) -> Pair | None:
    """The pair TrueFX names `EUR/USD` (its feed) or `EURUSD` (its history
    files); None for one it does not list."""
    named = text.strip().upper()
    return BY_SYMBOL.get(named) or BY_KEY.get(named)


@dataclass
class PairMap:
    """The pair map, kept in the plugin's storage: each currency code's cash
    instrument, the codes that did not resolve and why, and each subject
    named by reading its record."""

    path: Path | None = None
    #: ISO code -> the deployment's cash instrument it resolved to.
    ids: dict[str, str] = field(default_factory=dict)
    #: ISO code -> why it did not resolve (a MissReason's name).
    missing: dict[str, str] = field(default_factory=dict)
    #: Subject -> the ISO code its record carries, for a subject the lake
    #: asked for whose ID is not one the plugin resolved.
    subjects: dict[str, str] = field(default_factory=dict)
    read_at_ns: int = 0

    def load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            held = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as unreadable:
            log.warning("the pair map in storage was not read, made again: %s", unreadable)
            return
        self.ids = dict(held.get("ids", {}))
        self.missing = dict(held.get("missing", {}))
        self.subjects = dict(held.get("subjects", {}))
        self.read_at_ns = int(held.get("read_at_ns", 0))

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        kept = {
            "ids": self.ids,
            "missing": self.missing,
            "subjects": self.subjects,
            "read_at_ns": self.read_at_ns,
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(kept, indent=1, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)

    def code_of(self, subject: str) -> str:
        """The ISO code a subject is, as resolved or named; empty if neither."""
        for code, instrument in self.ids.items():
            if instrument == subject:
                return code
        return self.subjects.get(subject, "")

    def resolved(self, pair: Pair) -> bool:
        """Whether both of a pair's currencies resolved to cash instruments."""
        return bool(self.ids.get(pair.base)) and bool(self.ids.get(pair.quote))

    def subject_of(self, pair: Pair) -> str:
        """The base currency's cash instrument: a row's subject."""
        return self.ids.get(pair.base, "")
