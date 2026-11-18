"""One-minute bars on the live dataset (item 95): a standing want of bars
of 60 seconds kept current with one closed bar per pair per minute, the
open, high, low and close of the minute's mid, each recorded once as its
minute closes; a minute the plugin did not hear whole -- the one it started
in, one across a lost session -- never recorded; and any other length
declined as not covered."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from meridian.operations import as_decimal, as_money
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.suites import Recorder

from truefx.synthetic import Stated, Synthetic
from truefx.work import Work

from conftest import INSTANCE, ns, recorder, want, work_on

BAR = "meridian.v1.Bar"
MINUTE_NS = 60 * 10**9
#: 12:00 New York on Friday 9 October 2026, a whole minute.
T0 = ns("2026-10-09T16:00:00")
T0_MS = T0 // 10**6


def ms(seconds: float) -> int:
    return T0_MS + round(seconds * 1000)


def at(seconds: float) -> int:
    return T0 + round(seconds * 10**9)


@dataclass
class Clock:
    now: int = T0

    def __call__(self) -> int:
        return self.now


@dataclass
class Tick:
    seconds: float
    symbol: str
    bid: str
    ask: str


def feed(polls: list[float], ticks: list[Tick]) -> Synthetic:
    """The synthetic feed answering each poll, in turn, with the ticks
    stated since the poll before it."""
    steps: list[list[Stated]] = []
    before = float("-inf")
    for poll in polls:
        steps.append([Stated(t.symbol, str(ms(t.seconds)), t.bid, t.ask, t.ask, t.bid, t.bid)
                      for t in ticks if before < t.seconds <= poll])  # fmt: skip
        before = poll
    return Synthetic(feed=steps)


def working(root: Path, polls: list[float], ticks: list[Tick]) -> tuple[Work, Recorder, Clock]:
    lake = recorder()
    clock = Clock(at(polls[0]) - 10**9)
    work = work_on(lake, root, synthetic=feed(polls, ticks))
    work.clock_ns = work.client.clock_ns = clock
    return work, lake, clock


def run(work: Work, clock: Clock, polls: list[float]) -> None:
    """TrueFX polled at each time, each minute closed since kept current,
    as `keep_current` does each second."""
    for poll in polls:
        clock.now = at(poll)
        asyncio.run(work.poll_once())
        asyncio.run(work.keep_bars())


def hear(lake: Recorder, work: Work, *wants: ops.ObservationsWantedEvent) -> None:
    lake.answer("ObservationsWanted", lambda _: list(wants))
    asyncio.run(lake.hear(work))


def bars_wanted(want_id: str, subjects: list[str], *, standing: bool = True,
                interval_ns: int = MINUTE_NS) -> ops.ObservationsWantedEvent:  # fmt: skip
    return want(want_id, "live", subjects, data_type=BAR, standing=standing,
                interval_ns=interval_ns)  # fmt: skip


def bars(lake: Recorder) -> list[ops.Bar]:
    return [b for sent in lake.on("RecordBars") for b in sent.bars]


def ohlc(bar: ops.Bar) -> list[str]:
    return [str(as_money(getattr(bar, f)).amount) for f in ("open", "high", "low", "close")]


@dataclass
class Aged:
    """A stand-in for the plugin's `Latency`: each row it was given to age."""

    rows: list[Any] = field(default_factory=list)

    def aged(self, dataset: str, hop: str, row: Any) -> int:
        self.rows.append(row)
        return 0


def test_one_minute_of_polls_makes_one_bar_per_pair_with_the_minutes_ohlc(
    tmp_path: Path,
) -> None:
    polls = [30.2, *(60.5 + k for k in range(60)), 120.5]
    ticks = [
        Tick(30.0, "EUR/USD", "1.16430", "1.16434"),
        Tick(30.0, "USD/JPY", "149.510", "149.514"),
        Tick(30.0, "GBP/USD", "1.34610", "1.34614"),
        # 12:01: EUR/USD's open, high, low and close of the mid; USD/JPY once;
        # GBP/USD not at all.
        Tick(60.2, "EUR/USD", "1.16440", "1.16444"),
        Tick(61.0, "USD/JPY", "149.520", "149.524"),
        Tick(75.0, "EUR/USD", "1.16470", "1.16474"),
        Tick(90.0, "EUR/USD", "1.16400", "1.16404"),
        Tick(119.0, "EUR/USD", "1.16450", "1.16454"),
        # 12:02, forming: no bar yet.
        Tick(120.2, "EUR/USD", "1.16460", "1.16464"),
    ]
    work, lake, clock = working(tmp_path, polls, ticks)
    aged = Aged()
    work.latency = aged
    hear(lake, work, bars_wanted("WNT-1", ["LCL-EUR", "LCL-USD", "LCL-GBP"]))
    # Kept current from the next minute closed: nothing to record yet, and
    # nothing declined.
    assert lake.on("RecordBars") == [] and lake.on("DeclineWant") == []
    run(work, clock, polls)
    recorded = {b.meta.row_key: b for b in bars(lake)}
    # 12:00, the minute it started in, was not heard whole: no bar.
    assert sorted(recorded) == [f"EURUSD:1m:{ms(60)}", f"USDJPY:1m:{ms(60)}"]
    assert len(bars(lake)) == 2, "each bar recorded once"
    euro = recorded[f"EURUSD:1m:{ms(60)}"]
    assert ohlc(euro) == ["1.16442", "1.16472", "1.16402", "1.16452"]
    assert as_money(euro.close).currency_code == "USD"
    assert str(as_decimal(euro.volume)) == "0" and not euro.HasField("vwap")
    assert (euro.meta.valid_from_ns, euro.meta.valid_until_ns) == (at(60), at(120))
    assert euro.meta.valid_until_ns - euro.meta.valid_from_ns == MINUTE_NS
    times = {t.kind: t.at_ns for t in euro.meta.source_times}
    assert times == {ops.SOURCE_TIME_KIND_PUBLISHED: at(120),
                     ops.SOURCE_TIME_KIND_EVENT: at(119)}  # fmt: skip
    assert euro.meta.business_date == "" and euro.meta.source.venue_id == ""
    assert euro.meta.source.dataset == f"{INSTANCE}:live"
    assert euro.meta.subjects[0].entity_id == "LCL-EUR"
    assert euro.meta.raw.key.startswith("responses/")
    dollar = recorded[f"USDJPY:1m:{ms(60)}"]
    assert ohlc(dollar) == ["149.522"] * 4 and as_money(dollar.close).currency_code == "JPY"
    assert dollar.meta.subjects[0].entity_id == "LCL-USD"
    # Kept current for the standing want: recorded unasked.
    assert {sent.want_id for sent in lake.on("RecordBars")} == {""}
    # The live dataset's edge age stays the quotes' own: no bar is aged.
    assert aged.rows == []


def test_a_minute_with_no_ticks_makes_no_bar_and_a_want_before_one_closed_is_silent(
    tmp_path: Path,
) -> None:
    polls = [30.2, 60.5, 100.0, 130.0, 190.5, 240.5]
    ticks = [
        Tick(30.0, "EUR/USD", "1.16430", "1.16434"),
        Tick(70.0, "EUR/USD", "1.16440", "1.16444"),
        # Nothing in 12:02.
        Tick(185.0, "EUR/USD", "1.16450", "1.16454"),
    ]
    work, lake, clock = working(tmp_path, polls, ticks)
    hear(lake, work, bars_wanted("WNT-1", ["LCL-EUR"], standing=False))
    [declined] = lake.on("DeclineWant")
    assert declined.reason == ops.UNANSWERED_REASON_SOURCE_SILENT
    assert lake.on("RecordBars") == []
    hear(lake, work, bars_wanted("WNT-2", ["LCL-EUR"]))
    run(work, clock, polls)
    assert [b.meta.row_key for b in bars(lake)] == [f"EURUSD:1m:{ms(60)}", f"EURUSD:1m:{ms(180)}"]
    # Asked once, the latest closed minute is recorded against the want.
    lake.sent.clear()
    hear(lake, work, bars_wanted("WNT-3", ["LCL-EUR"], standing=False))
    [sent] = lake.on("RecordBars")
    assert sent.want_id == "WNT-3"
    assert [b.meta.row_key for b in sent.bars] == [f"EURUSD:1m:{ms(180)}"]
    assert lake.on("DeclineWant") == []


def test_a_restart_mid_minute_records_no_bar_twice(tmp_path: Path) -> None:
    before = [30.2, 70.5, 110.5, 120.5, 140.5]
    ticks = [
        Tick(30.0, "EUR/USD", "1.16430", "1.16434"),
        Tick(30.0, "USD/JPY", "149.510", "149.514"),
        Tick(70.0, "EUR/USD", "1.16440", "1.16444"),
        Tick(110.0, "USD/JPY", "149.520", "149.524"),
        Tick(140.0, "EUR/USD", "1.16450", "1.16454"),
    ]
    work, lake, clock = working(tmp_path, before, ticks)
    hear(lake, work, bars_wanted("WNT-1", ["LCL-EUR", "LCL-USD"]))
    run(work, clock, before)
    first = [b.meta.row_key for b in bars(lake)]
    assert sorted(first) == [f"EURUSD:1m:{ms(60)}", f"USDJPY:1m:{ms(60)}"]
    # Restarted at 12:02:45, mid-minute: TrueFX's snapshot answers each
    # pair's latest tick -- EUR/USD's at 12:02:20, USD/JPY's at 12:01:50,
    # whose minute was recorded -- then EUR/USD moves on.
    after = [150.5, 160.5, 190.5, 240.5]
    later = [
        Tick(140.0, "EUR/USD", "1.16450", "1.16454"),
        Tick(110.0, "USD/JPY", "149.520", "149.524"),
        Tick(160.0, "EUR/USD", "1.16460", "1.16464"),
        Tick(190.0, "EUR/USD", "1.16470", "1.16474"),
    ]
    again = recorder()
    restarted = work_on(again, tmp_path, synthetic=feed(after, later))
    restarted.clock_ns = restarted.client.clock_ns = clock
    clock.now = at(150.0)
    hear(again, restarted, bars_wanted("WNT-1", ["LCL-EUR", "LCL-USD"]))
    run(restarted, clock, after)
    second = [b.meta.row_key for b in bars(again)]
    # 12:02 was heard whole by neither process; 12:01 not again; 12:03 once.
    assert second == [f"EURUSD:1m:{ms(180)}"]
    assert sorted(first + second) == sorted(set(first + second))


def test_a_minute_across_a_lost_session_is_not_recorded(tmp_path: Path) -> None:
    answered = [30.2, 70.5, 91.5, 130.5, 180.5]
    ticks = [
        Tick(30.0, "EUR/USD", "1.16430", "1.16434"),
        Tick(70.0, "EUR/USD", "1.16440", "1.16444"),
        Tick(91.0, "EUR/USD", "1.16450", "1.16454"),
        Tick(125.0, "EUR/USD", "1.16460", "1.16464"),
    ]
    work, lake, clock = working(tmp_path, answered, ticks)
    hear(lake, work, bars_wanted("WNT-1", ["LCL-EUR"]))
    run(work, clock, answered[:2])
    held = work.client.transport

    def refused(url: str) -> object:
        raise ConnectionRefusedError(61, "Connection refused")

    work.client.transport = refused  # type: ignore[assignment]
    run(work, clock, [90.5])
    work.client.transport = held
    run(work, clock, answered[2:])
    # 12:01 lost a poll: not heard whole, so no bar; 12:02 heard whole.
    assert [b.meta.row_key for b in bars(lake)] == [f"EURUSD:1m:{ms(120)}"]
    [bar] = bars(lake)
    assert ohlc(bar) == ["1.16462"] * 4


def test_bars_of_a_minute_alone_any_other_length_not_covered(tmp_path: Path) -> None:
    work, lake, _ = working(tmp_path, [30.2], [Tick(30.0, "EUR/USD", "1.16430", "1.16434")])
    hear(
        lake,
        work,
        bars_wanted("WNT-1", ["LCL-EUR"], interval_ns=5 * MINUTE_NS),
        bars_wanted("WNT-2", ["LCL-EUR"], interval_ns=10**9),
        bars_wanted("WNT-3", ["LCL-EUR"]),
        # No length named: the one live serves, a minute.
        bars_wanted("WNT-4", ["LCL-EUR"], interval_ns=0),
    )
    declined = {d.want_id: d.reason for d in lake.on("DeclineWant")}
    assert declined == {"WNT-1": ops.UNANSWERED_REASON_NOT_COVERED,
                        "WNT-2": ops.UNANSWERED_REASON_NOT_COVERED}  # fmt: skip
    assert sorted(work.standing) == ["WNT-3", "WNT-4"]
