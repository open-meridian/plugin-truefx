"""The plugin's work on the synthetic feed: what it records, exactly, under
which keys and times; what it declines and why; and what it reports."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import date
from pathlib import Path

from meridian.operations import as_decimal, as_money
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.suites import Recorder

from truefx.days import day_bounds
from truefx.work import Work

from conftest import FORMING_NS, INSTANCE, LATER_NS, Records, ns, recorder, want, work_on


def hear(lake: Recorder, work: Work, *wants: ops.ObservationsWantedEvent) -> None:
    lake.answer("ObservationsWanted", lambda _: list(wants))
    asyncio.run(lake.receive(observations_wanted=work.on_want))


def prices(lake: Recorder) -> dict[str, ops.Price]:
    return {p.meta.row_key: p for sent in lake.on("RecordPrices") for p in sent.prices}


def amount(money: ops.Money) -> tuple[str, str]:
    held = as_money(money)
    return str(held.amount), held.currency_code


def test_a_days_close_from_trueFX_history_files_exactly(tmp_path: Path) -> None:
    lake = recorder()
    work = work_on(lake, tmp_path)
    hear(lake, work, want("WNT-1", "daily", ["LCL-EUR"], day="2026-10-08", data_type=""))
    rows = prices(lake)
    close = rows["EURUSD:close:2026-10-08"]
    assert amount(close.price) == ("1.163925", "USD")
    assert close.kind == ops.PRICE_KIND_CLOSE
    assert close.basis == ops.PRICE_BASIS_PER_UNIT
    assert close.meta.subjects[0].entity_id == "LCL-EUR"
    assert close.meta.business_date == "2026-10-08"
    assert close.meta.source.dataset == f"{INSTANCE}:daily"
    assert close.meta.source.venue_id == ""
    start, end = day_bounds(date(2026, 10, 8))
    assert (close.meta.valid_from_ns, close.meta.valid_until_ns) == (start, end)
    assert start == ns("2026-10-07T21:00:00") and end == ns("2026-10-08T21:00:00")
    times = {t.kind: t.at_ns for t in close.meta.source_times}
    assert times == {ops.SOURCE_TIME_KIND_PUBLISHED: end,
                     ops.SOURCE_TIME_KIND_EVENT: ns("2026-10-08T20:59:30")}  # fmt: skip
    assert close.meta.raw.key == "synthetic/history/EURUSD-2026-10.csv#29"
    assert amount(rows["EURUSD:bid:2026-10-08"].price) == ("1.16391", "USD")
    assert amount(rows["EURUSD:ask:2026-10-08"].price) == ("1.16394", "USD")
    # Every EUR pair the unauthenticated session serves with history: one.
    assert sorted(rows) == ["EURUSD:ask:2026-10-08", "EURUSD:bid:2026-10-08",
                            "EURUSD:close:2026-10-08"]  # fmt: skip
    [bar] = [b for sent in lake.on("RecordBars") for b in sent.bars]
    assert bar.meta.row_key == "EURUSD:1d:2026-10-08"
    assert [amount(getattr(bar, f))[0] for f in ("open", "high", "low", "close")] == [
        "1.16380", "1.163925", "1.16371", "1.163925"]  # fmt: skip
    assert str(as_decimal(bar.volume)) == "0" and not bar.HasField("vwap")
    assert lake.on("RecordPrices")[0].want_id == "WNT-1"


def test_the_dollar_is_priced_in_yen_as_trueFX_quotes_it_never_inverted(tmp_path: Path) -> None:
    lake = recorder()
    work = work_on(lake, tmp_path)
    hear(lake, work, want("WNT-1", "daily", ["LCL-USD", "LCL-JPY"], day="2026-10-08",
                          kinds=(ops.PRICE_KIND_CLOSE,)))  # fmt: skip
    rows = prices(lake)
    assert list(rows) == ["USDJPY:close:2026-10-08"]
    assert amount(rows["USDJPY:close:2026-10-08"].price) == ("149.380", "JPY")
    assert rows["USDJPY:close:2026-10-08"].meta.subjects[0].entity_id == "LCL-USD"
    [declined] = lake.on("DeclineWant")
    assert [s.entity_id for s in declined.subjects] == ["LCL-JPY"]
    assert declined.reason == ops.UNANSWERED_REASON_NOT_COVERED


def test_a_weekend_is_source_silent_and_before_the_files_beyond_history(tmp_path: Path) -> None:
    lake = recorder()
    work = work_on(lake, tmp_path)
    hear(
        lake,
        work,
        want("WNT-1", "daily", ["LCL-EUR"], day="2026-10-03"),
        want("WNT-2", "daily", ["LCL-EUR"], day="2026-09-15"),
        want("WNT-3", "daily", ["LCL-EUR"], day="2026-10-20"),
    )
    reasons = {d.want_id: d.reason for d in lake.on("DeclineWant")}
    assert reasons == {
        "WNT-1": ops.UNANSWERED_REASON_SOURCE_SILENT,
        "WNT-2": ops.UNANSWERED_REASON_BEYOND_HISTORY,
        "WNT-3": ops.UNANSWERED_REASON_SOURCE_SILENT,
    }
    assert lake.on("RecordPrices") == []


def test_the_forming_day_is_restated_under_the_same_keys_with_no_published_time(
    tmp_path: Path,
) -> None:
    lake = recorder()
    work = work_on(lake, tmp_path, now_ns=FORMING_NS)
    hear(lake, work, want("WNT-1", "daily", ["LCL-EUR"], data_type="", standing=True))
    lake.sent.clear()
    asyncio.run(work.poll_once())
    asyncio.run(work.keep_daily())
    asyncio.run(work.poll_once())
    asyncio.run(work.keep_daily())
    closes = [p for sent in lake.on("RecordPrices") for p in sent.prices
              if p.meta.row_key == "EURUSD:close:2026-10-09"]  # fmt: skip
    assert [amount(p.price)[0] for p in closes] == ["1.164325", "1.164385"]
    for close in closes:
        assert close.meta.valid_until_ns == day_bounds(date(2026, 10, 9))[1]
        assert [t.kind for t in close.meta.source_times] == [ops.SOURCE_TIME_KIND_EVENT]
    # The day's open stays the first tick's as the day fills.
    bars = [b for sent in lake.on("RecordBars") for b in sent.bars
            if b.meta.row_key == "EURUSD:1d:2026-10-09"]  # fmt: skip
    assert [amount(b.open)[0] for b in bars] == ["1.164325", "1.164325"]
    assert [amount(b.high)[0] for b in bars] == ["1.164325", "1.164385"]


def test_a_closed_day_is_pushed_once_for_every_pair_resolved(tmp_path: Path) -> None:
    lake = recorder()
    work = work_on(lake, tmp_path)
    for _ in range(4):
        asyncio.run(work.poll_once())
    assert asyncio.run(work.push_closed()) == 10 * 4
    assert asyncio.run(work.push_closed()) == 0
    rows = prices(lake)
    assert amount(rows["EURUSD:close:2026-10-09"].price) == ("1.164535", "USD")
    assert amount(rows["GBPJPY:close:2026-10-09"].price) == ("201.254", "JPY")
    assert rows["EURUSD:close:2026-10-09"].meta.raw.key.startswith("responses/2026-10-")
    resolved = [i.value for sent in lake.on("ResolveIdentifier") for i in sent.identifiers]
    assert sorted(resolved) == ["AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "USD"]


def test_a_closed_day_gaining_a_late_tick_is_pushed_again_restated(tmp_path: Path) -> None:
    lake = recorder()
    work = work_on(lake, tmp_path)
    asyncio.run(work.poll_once())
    asyncio.run(work.push_closed())
    asyncio.run(work.poll_once())  # step 1: EUR/USD and USD/JPY gained a tick
    assert asyncio.run(work.push_closed()) == 2 * 4
    closes = [p for sent in lake.on("RecordPrices") for p in sent.prices
              if p.meta.row_key == "EURUSD:close:2026-10-09"]  # fmt: skip
    assert [amount(p.price)[0] for p in closes] == ["1.164325", "1.164385"]


def test_a_currency_not_resolved_leaves_its_pairs_out_reported_once(tmp_path: Path) -> None:
    lake = recorder(Records(missing={"CHF"}))
    work = work_on(lake, tmp_path)
    asyncio.run(work.poll_once())
    asyncio.run(work.push_closed())
    asyncio.run(work.resolve_currencies())
    keys = {p.meta.row_key.split(":")[0] for p in prices(lake).values()}
    assert "USDCHF" not in keys and "EURCHF" not in keys and "EURUSD" in keys
    [missed] = lake.on("ReportMissingInstrument")
    assert [i.value for i in missed.identifiers] == ["CHF"]
    assert missed.reason == ops.MISS_REASON_NOT_FOUND


def test_live_records_the_top_of_book_as_a_quote_and_its_mid_as_a_price(tmp_path: Path) -> None:
    lake = recorder()
    work = work_on(lake, tmp_path)
    hear(lake, work, want("WNT-1", "live", ["LCL-EUR"], data_type=""))
    [quote] = [q for q in lake.on("RecordQuotes")[0].quotes if q.meta.row_key.startswith("EURUSD")]
    assert quote.meta.row_key == "EURUSD:q:1791547200003"
    assert (amount(quote.bid), amount(quote.ask)) == (("1.16431", "USD"), ("1.16434", "USD"))
    assert not quote.HasField("bid_quantity") and not quote.HasField("ask_quantity")
    assert quote.meta.business_date == "" and quote.meta.valid_from_ns == 1791547200003 * 10**6
    assert lake.on("RecordQuotes")[0].want_id == "WNT-1"
    mids = prices(lake)
    assert amount(mids["EURUSD:mid:1791547200003"].price) == ("1.164325", "USD")
    assert mids["EURUSD:mid:1791547200003"].kind == ops.PRICE_KIND_MID
    assert mids["EURUSD:mid:1791547200003"].meta.source.dataset == f"{INSTANCE}:live"
    # EUR/GBP, EUR/JPY and EUR/CHF too: each EUR pair, in its quote currency.
    assert sorted(k.split(":")[0] for k in mids) == ["EURCHF", "EURGBP", "EURJPY", "EURUSD"]


def test_a_standing_live_want_is_kept_current_from_each_poll(tmp_path: Path) -> None:
    lake = recorder()
    work = work_on(lake, tmp_path)
    hear(lake, work, want("WNT-1", "live", ["LCL-USD"], data_type="meridian.v1.Quote",
                          standing=True))  # fmt: skip
    lake.sent.clear()
    asyncio.run(work.keep_live())  # the first poll's rates, sent once more for the want
    asyncio.run(work.poll_once())  # step 1: USD/JPY moved
    asyncio.run(work.keep_live())
    asyncio.run(work.poll_once())  # step 2: only EUR/USD moved
    asyncio.run(work.keep_live())
    keys = [q.meta.row_key for sent in lake.on("RecordQuotes") for q in sent.quotes]
    assert keys == ["USDJPY:q:1791547200020", "USDCHF:q:1791547200071",
                    "USDCAD:q:1791547200122", "USDJPY:q:1791547201077"]  # fmt: skip
    assert lake.on("RecordPrices") == []
    work_withdrawn = ops.WantWithdrawnEvent(want_id="WNT-1", dataset=f"{INSTANCE}:live")
    lake.answer("WantWithdrawn", lambda _: work_withdrawn)
    asyncio.run(lake.receive(want_withdrawn=work.on_withdrawn))
    assert work.standing == {}


def test_each_answered_poll_is_the_live_datasets_liveness_while_a_want_stands(
    tmp_path: Path,
) -> None:
    # Contract v27 (ruling 418): with no standing want the live dataset is
    # not kept current, so nothing is confirmed; with one, each poll TrueFX
    # answers -- moved or not -- is recorded once, at the poll's time; a
    # poll that fails records nothing.
    lake = recorder()
    work = work_on(lake, tmp_path)
    ticks = iter(range(LATER_NS, LATER_NS + 100 * 10**9, 10**9))
    work.clock_ns = work.client.clock_ns = lambda: next(ticks)
    asyncio.run(work.poll_once())
    asyncio.run(work.keep_live())
    assert lake.on("RecordLiveness") == []
    hear(lake, work, want("WNT-1", "live", ["LCL-EUR"], data_type="meridian.v1.Quote",
                          standing=True))  # fmt: skip
    asyncio.run(work.keep_live())
    asyncio.run(work.keep_live())  # no poll between: nothing new to confirm
    asyncio.run(work.poll_once())
    polled = work.client.health.last_ok_ns
    asyncio.run(work.keep_live())

    def refused(url: str) -> object:
        raise ConnectionRefusedError(61, "Connection refused")

    work.client.transport = refused  # type: ignore[assignment]
    asyncio.run(work.poll_once())
    asyncio.run(work.keep_live())
    items = [item for sent in lake.on("RecordLiveness") for item in sent.liveness]
    assert [i.dataset for i in items] == [f"{INSTANCE}:live"] * 2
    assert items[-1].alive_at_ns == polled
    assert items[0].alive_at_ns < polled
    assert all(i.venue_id == "" for i in items)


def test_a_subject_another_source_resolved_is_named_by_reading_its_record(
    tmp_path: Path,
) -> None:
    lake = recorder()
    work = work_on(lake, tmp_path)
    hear(lake, work, want("WNT-1", "daily", ["LCL-custodian-eur", "LCL-custodian-qqq"],
                          day="2026-10-08", kinds=(ops.PRICE_KIND_CLOSE,)))  # fmt: skip
    rows = prices(lake)
    assert rows["EURUSD:close:2026-10-08"].meta.subjects[0].entity_id == "LCL-custodian-eur"
    assert [r.instrument_id for r in lake.on("ResolveInstrument")] == [
        "LCL-custodian-eur", "LCL-custodian-qqq"]  # fmt: skip
    [declined] = lake.on("DeclineWant")
    assert [s.entity_id for s in declined.subjects] == ["LCL-custodian-qqq"]


def test_an_authenticated_session_serves_twenty_seven_pairs(tmp_path: Path) -> None:
    lake = recorder()
    work = work_on(lake, tmp_path, username="jsTrader")
    asyncio.run(work.poll_once())
    assert len(work.client.pairs) == 27
    assert len(work.latest) == 10  # the synthetic feed's first step
    hear(lake, work, want("WNT-1", "live", ["LCL-NZD"], data_type=""))
    reasons = {d.reason for d in lake.on("DeclineWant")}
    assert reasons == {ops.UNANSWERED_REASON_SOURCE_SILENT}  # NZD/JPY and NZD/USD: silent


def test_a_want_of_a_kind_neither_dataset_holds_is_not_covered(tmp_path: Path) -> None:
    lake = recorder()
    work = work_on(lake, tmp_path)
    hear(
        lake,
        work,
        want("WNT-1", "daily", ["LCL-EUR"], day="2026-10-08", kinds=(ops.PRICE_KIND_NAV,)),
        want("WNT-2", "live", ["LCL-EUR"], kinds=(ops.PRICE_KIND_LAST,)),
        want("WNT-3", "daily", ["LCL-EUR"], day="2026-10-08", data_type="meridian.v1.Trade"),
    )
    assert {d.reason for d in lake.on("DeclineWant")} == {ops.UNANSWERED_REASON_NOT_COVERED}
    assert len(lake.on("DeclineWant")) == 3


def test_the_days_being_built_survive_a_restart(tmp_path: Path) -> None:
    lake = recorder()
    work = work_on(lake, tmp_path, now_ns=FORMING_NS)
    asyncio.run(work.poll_once())
    work.book.save()
    again = work_on(recorder(), tmp_path, now_ns=FORMING_NS)
    bar = again.book.get(work.client.pairs[0], date(2026, 10, 9))
    assert bar is not None and str(bar.close) == "1.164325" and bar.ticks == 1


def test_the_latest_daily_want_answers_the_past_week(tmp_path: Path) -> None:
    lake = recorder()
    work = work_on(lake, tmp_path, now_ns=LATER_NS)
    for _ in range(3):
        asyncio.run(work.poll_once())
    hear(lake, work, want("WNT-1", "daily", ["LCL-EUR"], kinds=(ops.PRICE_KIND_CLOSE,)))
    days = sorted(k.rsplit(":", 1)[1] for k in prices(lake) if k.startswith("EURUSD:close"))
    assert days == ["2026-10-07", "2026-10-08", "2026-10-09"]


class Stop(Exception):
    pass


def test_keeping_current_polls_each_second_and_waits_longer_while_trueFX_fails(
    tmp_path: Path,
) -> None:
    lake = recorder()
    work = work_on(lake, tmp_path)
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 3:

            def refused(url: str) -> object:
                raise ConnectionRefusedError(61, "Connection refused")

            work.client.transport = refused  # type: ignore[assignment]
        if len(slept) >= 12:
            raise Stop

    with contextlib.suppress(Stop):
        asyncio.run(work.keep_current(sleep))
    # Three polls a second apart; then, failing, waits of 2 and 4 seconds,
    # slept a second at a time, and the third failure's 8 cut off by Stop.
    assert slept == [1.0] * 12
    assert (work.client.health.calls, work.client.health.failures) == (6, 3)
    assert len(prices(lake)) == 30  # the 9th, pushed as it closed long ago
