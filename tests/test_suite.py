"""The data suite: the role's requirement, which this plugin holds itself to.

A plugin holding `data` is verified for it only by passing every case of the
suite the SDK carries (meridian.suites, contracts v18 to v22). Each case is
mapped to the plugin's own exchange with the synthetic TrueFX feed and its
history files (synthetic.py), run through the plugin's real client, rates,
days, history and work, against the SDK's `Recorder`: its typed operations
recorded rather than sent, answered as the deployment's records answer
(conftest.py).

A case about something TrueFX never states, or work this plugin never does,
is named in `NOT_PRESENTED` with why, and the runner holds it to being a case
about a kind of data or work (`about`) or a field (`about_field`):

- a crypto asset's price, prices on a venue, a security's price: TrueFX's
  API quotes currency pairs, indicative rates from Integral's network, no
  venue's, and no token or security;
- trades, and the cases about a trade's fields and a restart's gap of
  trades: nothing trades on TrueFX, whose rates are indicative;
- a quote with its sizes, and a one-sided quote: TrueFX states its bid and
  offer, both, on every rate, and never a size; its quotes are recorded with
  both sides and no size (test_work.py holds that);
- calendars and settlement dates: FX quotes need neither.

Every other case is mapped.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.suites import Recorder, run, suite

from conftest import FORMING_NS, INSTANCE, Records, recorder, want, work_on

Producer = Callable[[Recorder], Awaitable[None]]

NEVER_ABOUT = {
    "a crypto asset's price": "TrueFX quotes currency pairs: no token",
    "prices on a venue": "TrueFX's rates are indicative, from Integral's network: no venue's",
    "a security's price": "TrueFX quotes currency pairs: no security another source named",
    "trades": "nothing trades on TrueFX: its rates are indicative, so it states no trades",
    "calendars": "FX quotes need no settlement calendar: rates recorded as TrueFX states them",
    "settlement dates": "FX quotes need no settlement date: rates recorded as TrueFX states them",
}
NOT_PRESENTED: dict[str, str] = {
    case.name: NEVER_ABOUT[case.about] for case in suite("data").cases if case.about in NEVER_ABOUT
} | {
    "a-quote-recorded": "TrueFX states its bid and offer with no size: a quote's sizes are unset",
    "a-one-sided-quote": "TrueFX states both its bid and its offer on every rate it quotes",
}


def producers(root: Path) -> dict[str, Producer]:
    counter = iter(range(1_000_000))

    def fresh() -> Path:
        folder = root / f"case-{next(counter)}"
        folder.mkdir()
        return folder

    async def closed_day(lake: Recorder) -> None:
        # TrueFX polled three times on 9 October, then the day closed: its
        # rows recorded, every currency resolved first.
        Records().answering(lake)
        work = work_on(lake, fresh())
        for _ in range(3):
            await work.poll_once()
        await work.push_closed()

    async def forming(lake: Recorder) -> None:
        # 12:00 New York on 9 October, the day forming, read twice as it fills.
        Records().answering(lake)
        work = work_on(lake, fresh(), now_ns=FORMING_NS)
        for _ in range(2):
            await work.poll_once()
            await work.record_days(["LCL-EUR"], work.today(), work.today(), kinds=(1,))

    def wanted(message: ops.ObservationsWantedEvent, records: Records | None = None) -> Producer:
        async def produce(lake: Recorder) -> None:
            (records or Records()).answering(lake)
            work = work_on(lake, fresh())
            lake.answer("ObservationsWanted", lambda _: message)
            await lake.receive(observations_wanted=work.on_want)

        return produce

    async def ambiguous(lake: Recorder) -> None:
        # The euro's ISO code meets two of the deployment's records.
        Records(ambiguous={"EUR"}).answering(lake)
        work = work_on(lake, fresh())
        await work.poll_once()
        await work.resolve_currencies()

    async def withdrawn(lake: Recorder) -> None:
        work = work_on(lake, fresh())
        lake.answer(
            "WantWithdrawn",
            lambda _: [ops.WantWithdrawnEvent(want_id="WNT-1", dataset=f"{INSTANCE}:live")],
        )
        await lake.receive(want_withdrawn=work.on_withdrawn)

    async def licences(lake: Recorder) -> None:
        lake.answer(
            "ListDatasets",
            lambda _: ops.ListDatasetsResult(
                licences=[ops.DatasetLicence(dataset=f"{INSTANCE}:daily")]
            ),
        )
        work = work_on(lake, fresh())
        assert await work.read_licences() == {f"{INSTANCE}:daily"}

    day = want("WNT-1", "daily", ["LCL-EUR"], day="2026-10-08", kinds=(ops.PRICE_KIND_CLOSE,))
    bars = want("WNT-2", "daily", ["LCL-USD"], day="2026-10-08", data_type="meridian.v1.Bar")
    yen = want("WNT-3", "daily", ["LCL-JPY"], day="2026-10-08")
    return {
        "a-daily-close": closed_day,
        "the-forming-day-restated": forming,
        "an-exact-price": wanted(day),
        "a-daily-bar": wanted(bars),
        "an-fx-rate": wanted(day),
        "an-asset-that-does-not-resolve": ambiguous,
        "a-want-recorded-against": wanted(day),
        "a-subject-declined": wanted(yen),
        "a-standing-want-withdrawn": withdrawn,
        "reads-its-datasets-licences": licences,
    }


def test_every_case_of_the_data_suite_is_mapped_or_not_presented(tmp_path: Path) -> None:
    report = run("data", producers(tmp_path), not_presented=NOT_PRESENTED, instance_id=INSTANCE)
    assert report.passed, report.failures
    assert sorted(report.not_presented) == sorted(NOT_PRESENTED)
    assert len(report.passed_cases) == 10


def test_a_subject_declined_is_declined_as_not_covered_and_nothing_inverted(
    tmp_path: Path,
) -> None:
    # The yen's own instrument: no TrueFX pair has the yen as its base, and
    # USD/JPY is never inverted to make one.
    lake = recorder()
    work = work_on(lake, tmp_path)
    lake.answer("ObservationsWanted", lambda _: want("WNT-3", "daily", ["LCL-JPY"],
                                                     day="2026-10-08"))  # fmt: skip
    import asyncio

    asyncio.run(lake.receive(observations_wanted=work.on_want))
    assert lake.on("RecordPrices") == []
    [declined] = lake.on("DeclineWant")
    assert declined.reason == ops.UNANSWERED_REASON_NOT_COVERED
