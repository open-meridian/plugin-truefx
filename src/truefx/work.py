"""The data plugin's work (the role `data`): TrueFX's rates into the lake,
converted at the edge.

**Two datasets** (declaration.py): `live`, TrueFX's top of book as it polls
it, the bid and offer as a quote and the mid as a price; and `daily`, each
pair's day on New York's day ending at 17:00, built from TrueFX's ticks
(days.py) or from its history files where a person has put them in storage
(history.py): its close, its closing bid and offer, and its bar of the mid.

**A pair is two cash instruments** (pairs.py; ruled 2026-10-13, Q6). Each
currency TrueFX names is resolved through the master by its ISO 4217 code
(W3.1), the plugin's pair map kept in its storage; each subject the lake
asks for is the deployment's record, named as one of TrueFX's currencies by
its `iso4217` identifier, read where its ID is not one the plugin resolved
(W3.6). A subject is served by every pair TrueFX quotes with it as the base,
each row naming it as the subject and its price as a `Money` in the quote
currency, exactly as TrueFX quotes it: EUR/USD as the euro's price in
dollars, USD/JPY as the dollar's in yen (spec/the-lake, Q3). Nothing is
inverted or crossed, so the yen's own instrument, which no TrueFX pair has
as its base, is declined as not covered. A pair whose currency did not
resolve is left out, and the miss reported once (W3.2), never guessed.

**A row**: a live quote is keyed by its pair and TrueFX's millisecond
(`EURUSD:q:1791547200003`), its mid by the same with `mid`, valid from
TrueFX's time, its event time that time, with no business date; a quote
names no size, which TrueFX never states. A day's rows are keyed by the pair,
what they are and the business date (`EURUSD:close:2026-10-09`,
`EURUSD:bid:...`, `EURUSD:ask:...`, the bar `EURUSD:1d:...`), valid over
the day, so the day still forming is restated under the same keys as it
fills, and a closed day carries its `published` time, the day's end, and
its event time, its last tick's. Each names the raw record its last tick
was read from.

**Wants** (W10.7): the lake asks for a business date, a range or the latest
(the past week's days) of the daily dataset, or the latest of the live one,
for subjects; each subject is recorded against the want or declined:
`not_covered` where its record names none of TrueFX's currencies or no pair
TrueFX serves this session has it as the base, `beyond_history` before the
first day the plugin holds, `source_silent` where TrueFX said nothing for
it (a weekend, a day not reached yet). A standing want keeps its subjects
current until withdrawn: the live dataset from each poll, the daily
dataset's forming day every five minutes.

**Liveness** (contract v27, W10.4; ruling 418): while a standing want keeps
the live dataset current, each poll TrueFX answers is recorded as the live
dataset's sign of life (`RecordLiveness`), once a poll. An authenticated
session answers only the pairs that moved since the last poll, and nothing
while none did, so a poll answered with nothing is TrueFX's heartbeat: it
confirms every quote in force, and a reader judges a quote's age from the
later of its own time and that liveness. Without a standing want the live
dataset is not kept current, so nothing is confirmed.

**Pushed**: each day the plugin built is recorded once it closes, for every
pair TrueFX serves this session whose currencies resolved, wanted or not.

**Its licences** (contract v20, W10.9): read from the deployment on start and
each minute, so its Datasets page says "Licensed" or "Not licensed yet".
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import meridian
from meridian import Bar, Money, ObservationMeta, Price, Quote, SourceTime
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles.data.quality import EdgeChecks

from .client import TrueFX, latest
from .days import DayBar, DayBook, business_date, day_bounds
from .declared import DAILY, LIVE
from .history import History
from .pairs import Pair, PairMap, currencies
from .rates import Rate

log = logging.getLogger(__name__)

PRICE, BAR, QUOTE = "meridian.v1.Price", "meridian.v1.Bar", "meridian.v1.Quote"
_DAILY_KINDS = {ops.PRICE_KIND_CLOSE, ops.PRICE_KIND_BID, ops.PRICE_KIND_ASK}
_KIND_NAMES: dict[int, str] = {
    ops.PRICE_KIND_CLOSE: "close",
    ops.PRICE_KIND_BID: "bid",
    ops.PRICE_KIND_ASK: "ask",
}
#: TrueFX polled once a second; while it does not answer, at most a minute
#: apart.
POLL_SECONDS = 1.0
MOST_WAIT_SECONDS = 60.0
#: A standing want on the daily dataset: its forming day, every five minutes.
DAILY_EVERY_SECONDS = 300.0
#: The days being built written to storage, and the history files looked
#: at again, once a minute.
SAVE_EVERY_SECONDS = 60.0
#: Currencies that did not resolve, asked again once a day.
RESOLVE_AGAIN_SECONDS = 86_400.0
#: A want for the daily dataset's latest: the past week's days.
LATEST_DAYS = 7
#: The most days one want is answered for.
MOST_DAYS = 3660
#: The lake's batch: 1 to 500 rows.
BATCH = 500
#: How many of the wants heard the Datasets page lists.
RECENT = 200

Plugin = Any  # meridian.Plugin, or the suite's Recorder: the SDK's typed operations


@dataclass(frozen=True)
class Standing:
    """A standing want, kept current until it is withdrawn."""

    want_id: str
    key: str
    data_type: str
    subjects: tuple[str, ...]
    kinds: tuple[int, ...]


@dataclass(frozen=True)
class Heard:
    """One want as the Datasets page lists it."""

    want_id: str
    dataset: str
    asked: str
    subjects: int
    recorded: int
    declined: int
    standing: bool
    at_ns: int


@dataclass
class Counts:
    """What the plugin sent one dataset, or all, since it started."""

    recorded: int = 0
    restated: int = 0
    unchanged: int = 0
    declined: int = 0
    last_ns: int = 0


@dataclass
class Work:
    """The plugin's work: resolving, recording, and answering wants."""

    plugin: Plugin
    client: TrueFX
    pairs: PairMap
    book: DayBook
    history: History
    clock_ns: Callable[[], int] = time.time_ns
    standing: dict[str, Standing] = field(default_factory=dict)
    heard: deque[Heard] = field(default_factory=lambda: deque(maxlen=RECENT))
    counts: Counts = field(default_factory=Counts)
    by_dataset: dict[str, Counts] = field(default_factory=dict)
    licensed: frozenset[str] = frozenset()
    reads_licences: bool = True
    reads_instruments: bool = True
    #: Each pair's latest rate, and the time of the one last recorded live.
    latest: dict[Pair, Rate] = field(default_factory=dict)
    sent_live: dict[Pair, int] = field(default_factory=dict)
    #: The closed days pushed since it started, by pair and day: the last
    #: tick each was pushed with.
    pushed: dict[tuple[str, date], int] = field(default_factory=dict)
    #: Subjects whose record names none of TrueFX's currencies.
    unnamed: set[str] = field(default_factory=set)
    #: The live dataset's liveness last recorded (contract v27): the time of
    #: the poll TrueFX last answered, as the client kept it.
    liveness_ns: int = 0
    #: From 0.4.0 (contract v28, rulings 424 and 518): the plugin's
    #: `roles.Latency`, where it keeps one -- each row recorded unasked or
    #: for a standing want has its age at the edge recorded, its feed delay --
    #: and the SDK's edge checks, judging each such row (a crossed quote
    #: invalid), as the SDK's `Wants.record` does for the plugins on it.
    latency: Any = None
    quality: EdgeChecks = field(default_factory=EdgeChecks)

    def __post_init__(self) -> None:
        # The edge's checks on the plugin's clock, as it stands each time.
        self.quality.clock_ns = lambda: self.clock_ns()

    # ── Names ────────────────────────────────────────────────────────────

    def dataset(self, key: str) -> str:
        """A dataset as rows name it: the instance, a colon and the key."""
        return f"{self.plugin.identity.instance_id}:{key}"

    def _key_of(self, dataset: str) -> str:
        instance, _, key = dataset.partition(":")
        return key if instance == self.plugin.identity.instance_id else ""

    def sent_to(self, key: str) -> Counts:
        return self.by_dataset.setdefault(key, Counts())

    def use(self, client: TrueFX, pairs: PairMap, book: DayBook, history: History) -> None:
        """Answer from another source (sample data switched): its own pair
        map, days and history; standing wants carry over."""
        self.book.save()
        self.client, self.pairs, self.book, self.history = client, pairs, book, history
        self.latest, self.sent_live, self.pushed, self.unnamed = {}, {}, {}, set()

    # ── Licences ─────────────────────────────────────────────────────────

    async def read_licences(self) -> frozenset[str]:
        """Its own declared datasets' licences (contract v20, W10.9). A
        runtime that does not answer leaves each "Not licensed yet"."""
        if not self.reads_licences:
            return self.licensed
        try:
            answered = await self.plugin.list_datasets()
        except meridian.NotGranted:
            log.warning("this data plugin may not read its datasets' licences")
            self.reads_licences = False
            return self.licensed
        mine = {self.dataset(key) for key in (DAILY, LIVE)}
        self.licensed = frozenset(
            licence.dataset for licence in answered.licences if licence.dataset in mine
        )
        return self.licensed

    # ── Resolving ────────────────────────────────────────────────────────

    async def resolve_currencies(self, again: bool = False) -> None:
        """Resolve each currency the session's pairs name, not resolved yet,
        to the deployment's cash instrument, by its ISO 4217 code (W3.1); a
        miss reported once per reason (W3.2), and asked again only `again`
        (once a day)."""
        now = self.clock_ns()
        changed = False
        for code in currencies(self.client.pairs):
            if code in self.pairs.ids or (code in self.pairs.missing and not again):
                continue
            named = [meridian.Identifier(scheme="iso4217", value=code)]
            found = await self.plugin.resolve_identifier(
                identifiers=named, as_of_ns=now, stated_asset_class="cash"
            )
            changed = True
            if found.found and found.instrument_id:
                self.pairs.ids[code] = found.instrument_id
                self.pairs.missing.pop(code, None)
                continue
            miss = found.miss_reason or ops.MISS_REASON_NOT_FOUND
            reason = ops.MissReason.Name(miss)
            if self.pairs.missing.get(code) != reason:
                await self.plugin.report_missing_instrument(
                    source="truefx",
                    asset_class="cash",
                    identifiers=named,
                    as_of_ns=now,
                    reason=miss,
                    observed_at_ns=now,
                )
            self.pairs.missing[code] = reason
        if changed:
            self.pairs.read_at_ns = now
            self.pairs.save()

    async def code_of(self, subject: str) -> str:
        """The ISO code a subject is: one the plugin resolved, or read from
        its record (W3.6); empty where its record names none of TrueFX's
        currencies, or cannot be read."""
        known = self.pairs.code_of(subject)
        if known or subject in self.unnamed or not self.reads_instruments:
            return known
        try:
            found = await self.plugin.resolve_instrument(
                instrument_id=subject, as_of_ns=self.clock_ns()
            )
        except meridian.NotGranted:
            log.warning("this data plugin may not read an instrument's record")
            self.reads_instruments = False
            return ""
        offered = set(currencies(self.client.pairs))
        code = ""
        if found.found:
            code = next(
                (i.value.upper() for i in found.instrument.identifiers
                 if i.scheme == "iso4217" and i.value.upper() in offered),
                "",
            )  # fmt: skip
        if not code:
            self.unnamed.add(subject)
            return ""
        self.pairs.subjects[subject] = code
        self.pairs.save()
        return code

    def pairs_of(self, code: str) -> list[Pair]:
        """The session's pairs with `code` as the base, both currencies
        resolved."""
        return [p for p in self.client.pairs if p.base == code and self.pairs.resolved(p)]

    async def serving(self, subjects: Iterable[str]) -> dict[str, list[Pair]]:
        """Each subject's pairs: none where it is not covered."""
        await self.resolve_currencies()
        served: dict[str, list[Pair]] = {}
        for subject in subjects:
            code = await self.code_of(subject)
            served[subject] = self.pairs_of(code) if code else []
        return served

    # ── Rows ─────────────────────────────────────────────────────────────

    def _meta(
        self,
        row_key: str,
        subject: str,
        key: str,
        valid_from_ns: int,
        valid_until_ns: int,
        times: list[SourceTime],
        raw_key: str,
        business: date | None = None,
    ) -> ObservationMeta:
        return ObservationMeta(
            row_key=row_key,
            subjects=[meridian.SubjectRef(entity_id=subject)],
            source=ops.Source(dataset=self.dataset(key)),
            valid_from_ns=valid_from_ns,
            valid_until_ns=valid_until_ns,
            business_date=business or "",
            source_times=times,
            raw=self.plugin.raw_record(raw_key),
        )

    def quote(self, subject: str, rate: Rate) -> Quote:
        """TrueFX's top of book: its bid and offer, with no size."""
        times = [SourceTime(kind="event", at_ns=rate.at_ns)]
        return Quote(
            meta=self._meta(
                f"{rate.pair.key}:q:{rate.at_ms}", subject, LIVE, rate.at_ns, 0, times, rate.raw_key
            ),  # fmt: skip
            bid=Money(rate.bid, rate.pair.quote),
            ask=Money(rate.ask, rate.pair.quote),
        )

    def mid(self, subject: str, rate: Rate) -> Price:
        """The mid of TrueFX's top of book, at its time."""
        times = [SourceTime(kind="event", at_ns=rate.at_ns)]
        return Price(
            meta=self._meta(
                f"{rate.pair.key}:mid:{rate.at_ms}",
                subject,
                LIVE,
                rate.at_ns,
                0,
                times,
                rate.raw_key,
            ),  # fmt: skip
            kind="mid",
            price=Money(rate.mid, rate.pair.quote),
            basis="per_unit",
        )

    def _day_meta(self, row_key: str, subject: str, bar: DayBar) -> ObservationMeta:
        start, end = day_bounds(bar.day)
        times = [SourceTime(kind="event", at_ns=bar.last_ns)]
        if end <= self.clock_ns():
            times.insert(0, SourceTime(kind="published", at_ns=end))
        return self._meta(row_key, subject, DAILY, start, end, times, bar.raw_key, bar.day)

    def day_rows(
        self, subject: str, bar: DayBar, data_type: str = "", kinds: Iterable[int] = ()
    ) -> tuple[list[Price], list[Bar]]:
        """A day's close, closing bid and offer, and bar of the mid, as wanted."""
        pair, day = bar.symbol, bar.day.isoformat()
        asked = set(kinds) & _DAILY_KINDS or _DAILY_KINDS
        prices: list[Price] = []
        if data_type in ("", PRICE):
            amounts: dict[int, Decimal] = {
                ops.PRICE_KIND_CLOSE: bar.close,
                ops.PRICE_KIND_BID: bar.bid,
                ops.PRICE_KIND_ASK: bar.ask,
            }
            for kind in sorted(asked):
                name = _KIND_NAMES[kind]
                prices.append(
                    Price(
                        meta=self._day_meta(f"{pair.key}:{name}:{day}", subject, bar),
                        kind=name,
                        price=Money(amounts[kind], pair.quote),
                        basis="per_unit",
                    )
                )
        bars: list[Bar] = []
        if data_type in ("", BAR):
            bars.append(
                Bar(
                    meta=self._day_meta(f"{pair.key}:1d:{day}", subject, bar),
                    open=Money(bar.open, pair.quote),
                    high=Money(bar.high, pair.quote),
                    low=Money(bar.low, pair.quote),
                    close=Money(bar.close, pair.quote),
                    # Indicative quotes: nothing trades on TrueFX.
                    volume=Decimal(0),
                )
            )
        return prices, bars

    # ── Recording ────────────────────────────────────────────────────────

    def _count(self, done: Any, key: str) -> None:
        now = self.clock_ns()
        for counted in (self.counts, self.sent_to(key)):
            counted.recorded += int(getattr(done, "recorded", 0))
            counted.restated += int(getattr(done, "restated", 0))
            counted.unchanged += int(getattr(done, "unchanged", 0))
            counted.last_ns = now

    async def send(
        self,
        key: str,
        prices: Sequence[Price] = (),
        bars: Sequence[Bar] = (),
        quotes: Sequence[Quote] = (),
        want_id: str = "",
    ) -> None:
        """Rows recorded in batches of at most BATCH, against a want where
        they answer one. Rows recorded unasked or for a standing want are
        aged and judged at the edge first (contract v28)."""
        if not want_id or want_id in self.standing:
            if self.latency is not None:
                for row in (*prices, *bars, *quotes):
                    self.latency.aged(self.dataset(key), "AGE_HOP_EDGE", row)
            prices = self.quality.judged(key, prices)
            bars = self.quality.judged(key, bars)
            quotes = self.quality.judged(key, quotes)
        for at in range(0, len(prices), BATCH):
            done = await self.plugin.record_prices(
                prices=list(prices[at : at + BATCH]), want_id=want_id
            )
            self._count(done, key)
        for at in range(0, len(bars), BATCH):
            done = await self.plugin.record_bars(bars=list(bars[at : at + BATCH]), want_id=want_id)
            self._count(done, key)
        for at in range(0, len(quotes), BATCH):
            done = await self.plugin.record_quotes(
                quotes=list(quotes[at : at + BATCH]), want_id=want_id
            )
            self._count(done, key)

    def day_bar(self, pair: Pair, day: date) -> DayBar | None:
        """A pair's day: from TrueFX's history files where they hold it,
        else as the plugin built it from its polls."""
        return self.history.bar(pair, day) or self.book.get(pair, day)

    def first_day(self, pair: Pair) -> date | None:
        """The first business date the plugin holds for a pair."""
        built = next((d for d in self.book.held_days() if self.book.get(pair, d)), None)
        held = [d for d in (self.history.first_day(pair), built) if d]
        return min(held) if held else None

    def today(self) -> date:
        return business_date(self.clock_ns())

    async def record_days(
        self,
        subjects: Iterable[str],
        first: date,
        last: date,
        data_type: str = "",
        kinds: Iterable[int] = (),
        want_id: str = "",
    ) -> dict[str, str]:
        """Each subject's days from `first` to `last`, from every pair it is
        the base of; what was declined, by subject and reason."""
        today = self.today()
        last = min(last, today, first + timedelta(days=MOST_DAYS - 1))
        kinds = tuple(kinds)
        declined: dict[str, str] = {}
        prices: list[Price] = []
        bars: list[Bar] = []
        for subject, pairs in (await self.serving(subjects)).items():
            if not pairs:
                declined[subject] = "not_covered"
                continue
            if first > today:
                declined[subject] = "source_silent"
                continue
            found = 0
            for pair in pairs:
                day = first
                while day <= last:
                    bar = self.day_bar(pair, day)
                    if bar is not None:
                        more_prices, more_bars = self.day_rows(subject, bar, data_type, kinds)
                        prices += more_prices
                        bars += more_bars
                        found += len(more_prices) + len(more_bars)
                    day += timedelta(days=1)
            if not found:
                reached = [d for d in (self.first_day(p) for p in pairs) if d]
                before = last < min(reached) if reached else last < today
                declined[subject] = "beyond_history" if before else "source_silent"
        await self.send(DAILY, prices, bars, want_id=want_id)
        return declined

    async def record_live(
        self, subjects: Iterable[str], data_type: str = "", want_id: str = ""
    ) -> dict[str, str]:
        """Each subject's latest top of book from every pair it is the base
        of: a quote, its mid, or both, as wanted."""
        served = await self.serving(subjects)
        if any(served.values()) and not self.latest:
            await self.poll_once()
        declined: dict[str, str] = {}
        prices: list[Price] = []
        quotes: list[Quote] = []
        for subject, pairs in served.items():
            if not pairs:
                declined[subject] = "not_covered"
                continue
            rates = [self.latest[p] for p in pairs if p in self.latest]
            if not rates:
                declined[subject] = "source_silent"
                continue
            for rate in rates:
                if data_type in ("", QUOTE):
                    quotes.append(self.quote(subject, rate))
                if data_type in ("", PRICE):
                    prices.append(self.mid(subject, rate))
        await self.send(LIVE, prices, quotes=quotes, want_id=want_id)
        return declined

    # ── Wants ────────────────────────────────────────────────────────────

    @staticmethod
    def serves(key: str, data_type: str, kinds: tuple[int, ...]) -> bool:
        """Whether a want of `data_type` and `kinds` asks of `key` what it holds."""
        if key == DAILY:
            return data_type in ("", PRICE, BAR) and (not kinds or bool(set(kinds) & _DAILY_KINDS))
        if key == LIVE:
            if data_type == QUOTE:
                return True
            return data_type in ("", PRICE) and (not kinds or ops.PRICE_KIND_MID in kinds)
        return False

    async def _decline(self, want_id: str, declined: dict[str, str], key: str) -> None:
        by_reason: dict[str, list[str]] = {}
        for subject, reason in declined.items():
            by_reason.setdefault(reason, []).append(subject)
        for reason, subjects in sorted(by_reason.items()):
            await self.plugin.decline_want(
                want_id=want_id,
                subjects=[meridian.SubjectRef(entity_id=s) for s in subjects],
                reason=reason,
            )
            self.counts.declined += len(subjects)
            self.sent_to(key).declined += len(subjects)

    async def on_want(self, heard: meridian.Heard[ops.ObservationsWantedEvent]) -> None:
        """Record what the lake wants, or decline it per subject."""
        want = heard.message
        subjects = [s.entity_id for s in want.subjects]
        key = self._key_of(want.dataset)
        kinds = tuple(want.kinds)
        before = self.counts.recorded + self.counts.restated + self.counts.unchanged
        asked = want.business_date or (
            f"{want.valid_from_ns}..{want.valid_until_ns}" if want.valid_from_ns else "latest"
        )
        try:
            declined = await self._answer(want, key, subjects, kinds)
        except Exception as failed:  # noqa: BLE001 - TrueFX or the lake refused; said, not raised
            log.warning("want %s not answered: %s", want.want_id, failed)
            declined = {s: "source_silent" for s in subjects}
        await self._decline(want.want_id, declined, key)
        after = self.counts.recorded + self.counts.restated + self.counts.unchanged
        self.heard.appendleft(
            Heard(want.want_id, want.dataset, asked, len(subjects), after - before,
                  len(declined), want.standing, self.clock_ns())
        )  # fmt: skip

    async def _answer(
        self, want: ops.ObservationsWantedEvent, key: str, subjects: list[str],
        kinds: tuple[int, ...],
    ) -> dict[str, str]:  # fmt: skip
        if not self.serves(key, want.data_type, kinds):
            return {s: "not_covered" for s in subjects}
        if want.standing:
            self.standing[want.want_id] = Standing(
                want.want_id, key, want.data_type, tuple(subjects), kinds
            )
        if key == LIVE:
            return await self.record_live(subjects, want.data_type, want.want_id)
        if want.business_date:
            day = date.fromisoformat(want.business_date)
            return await self.record_days(subjects, day, day, want.data_type, kinds, want.want_id)
        if want.valid_from_ns:
            until = want.valid_until_ns or self.clock_ns()
            first = business_date(want.valid_from_ns)
            last = business_date(max(until - 1, want.valid_from_ns))
            return await self.record_days(subjects, first, last, want.data_type, kinds,
                                          want.want_id)  # fmt: skip
        today = self.today()
        first = today - timedelta(days=LATEST_DAYS - 1)
        return await self.record_days(subjects, first, today, want.data_type, kinds, want.want_id)

    async def on_withdrawn(self, heard: meridian.Heard[ops.WantWithdrawnEvent]) -> None:
        """A standing want withdrawn: its subjects are no longer kept current."""
        self.standing.pop(heard.message.want_id, None)

    # ── Polling and keeping current ──────────────────────────────────────

    async def poll_once(self) -> int:
        """One poll of TrueFX: each tick into its pair's day and kept as the
        pair's latest. Answers how many ticks were new."""
        read = await asyncio.to_thread(self.client.poll)
        new = 0
        for rate in sorted(read.rates, key=lambda r: r.at_ms):
            if self.book.add(rate):
                new += 1
        self.latest.update(latest(read.rates))
        return new

    async def keep_live(self) -> None:
        """The live dataset's standing wants: each subject's pairs whose
        rate moved since last recorded, recorded."""
        wants = [w for w in self.standing.values() if w.key == LIVE]
        if not wants:
            return
        prices: list[Price] = []
        quotes: list[Quote] = []
        moved: dict[Pair, int] = {}
        for want in wants:
            for subject, pairs in (await self.serving(want.subjects)).items():
                for pair in pairs:
                    rate = self.latest.get(pair)
                    if rate is None or rate.at_ms <= self.sent_live.get(pair, -1):
                        continue
                    moved[pair] = rate.at_ms
                    if want.data_type in ("", QUOTE):
                        quotes.append(self.quote(subject, rate))
                    if want.data_type in ("", PRICE):
                        prices.append(self.mid(subject, rate))
        await self.send(LIVE, prices, quotes=quotes)
        self.sent_live.update(moved)
        await self.alive()

    async def alive(self) -> bool:
        """The live dataset's sign of life (contract v27; ruling 418): the
        last poll TrueFX answered, moved or not, recorded once a poll -- it
        confirms every quote in force. Whether it was recorded; a poll that
        failed records nothing, and a refusal is said, never raised."""
        alive_ns = self.client.health.last_ok_ns
        if alive_ns <= self.liveness_ns:
            return False
        self.liveness_ns = alive_ns
        try:
            await self.plugin.record_liveness(
                liveness=[ops.DatasetLiveness(dataset=self.dataset(LIVE), alive_at_ns=alive_ns)]
            )
        except (meridian.MeridianError, ValueError) as refused:
            log.warning("the live dataset's liveness not recorded: %s", refused)
            return False
        return True

    async def keep_daily(self) -> None:
        """The daily dataset's standing wants: yesterday and the forming day."""
        today = self.today()
        for want in [w for w in self.standing.values() if w.key == DAILY]:
            await self.record_days(want.subjects, today - timedelta(days=1), today,
                                   want.data_type, want.kinds)  # fmt: skip

    async def push_closed(self) -> int:
        """Each closed day the book holds that is not pushed yet, or has
        gained a tick since (a tick TrueFX states late), for every pair the
        session serves whose currencies resolved: recorded, wanted or not."""
        now = self.clock_ns()
        closed = [d for d in sorted(self.book.days) if day_bounds(d)[1] <= now]
        due = [
            (pair, day)
            for day in closed
            for pair in self.client.pairs
            if (held := self.book.get(pair, day)) is not None
            and self.pushed.get((pair.key, day), -1) < held.last_ns
        ]
        if not due:
            return 0
        await self.resolve_currencies()
        prices: list[Price] = []
        bars: list[Bar] = []
        for pair, day in due:
            bar = self.day_bar(pair, day)
            if bar is None or not self.pairs.resolved(pair):
                continue
            more_prices, more_bars = self.day_rows(self.pairs.subject_of(pair), bar)
            prices += more_prices
            bars += more_bars
            built = self.book.get(pair, day)
            self.pushed[(pair.key, day)] = built.last_ns if built else bar.last_ns
        await self.send(DAILY, prices, bars)
        return len(prices) + len(bars)

    async def keep_current(self, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        """Poll TrueFX once a second until cancelled: the live standing wants
        kept current, each closed day pushed, the daily standing wants'
        forming day every five minutes, and once a minute the days being
        built saved and the history files looked at again. While TrueFX
        does not answer, it is asked again after 2, 4, 8 ... seconds, at
        most a minute apart."""
        last_daily = last_saved = 0.0
        last_resolved = time.monotonic()
        failing = 0
        while True:
            now = time.monotonic()
            failures = self.client.health.failures
            try:
                if now - last_resolved >= RESOLVE_AGAIN_SECONDS:
                    await self.resolve_currencies(again=True)
                    last_resolved = now
                await self.poll_once()
                await self.keep_live()
                await self.push_closed()
                if now - last_daily >= DAILY_EVERY_SECONDS:
                    await self.keep_daily()
                    last_daily = now
                if now - last_saved >= SAVE_EVERY_SECONDS:
                    self.book.save()
                    await asyncio.to_thread(self.history.refresh)
                    last_saved = now
            except Exception as failed:  # noqa: BLE001 - said, and tried again next time
                log.warning("keeping current stopped this time: %s", failed)
            failing = failing + 1 if self.client.health.failures > failures else 0
            wait = min(MOST_WAIT_SECONDS, 2.0**failing) if failing else POLL_SECONDS
            # A wait cut short where the source changed (sample data switched).
            client = self.client
            while wait > 0 and self.client is client:
                await sleep(min(POLL_SECONDS, wait))
                wait -= POLL_SECONDS


async def cancelled(task: asyncio.Task[Any]) -> None:
    """Cancel a task and wait for it."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
