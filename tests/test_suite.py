"""The data suite: the role's requirement, which this plugin holds itself to.

A plugin holding `data` is verified for it only by passing every case of the
suite the SDK carries (meridian.suites, contracts v18 to v27). Each case is
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
- calendars and settlement dates: FX quotes need neither;
- an event contract's outcomes, disputed or not (contract v23, and v26's
  event group and flag cases, about outcomes): TrueFX lists no event
  contract;
- contract v27's rates cases (about rates): TrueFX quotes currency pairs,
  recorded as prices and quotes, and publishes no reference rate's fixing,
  curve or index level;
- `queries-the-lake-within-bounds`, about trades from contract v27: it
  records no trades (and asks the lake nothing);
- from contract v28, option chains, filings, holdings, dividends and
  ratings, which TrueFX never states; and the duplicate and gap cases
  (about quotes): its rates are polled and number no message.

From contract v28 `reports-its-feed-delay` (ruling 518) and
`a-crossed-quote-is-recorded-invalid` (ruling 424) are presented: quotes
kept current for a standing want, aged and judged at the edge (work.py).

Every other case is mapped. Contract v27's `records-a-datasets-liveness`
is presented: with a standing want on the live dataset, an authenticated
session's poll answered with nothing moved is TrueFX's heartbeat, recorded
as the live dataset's liveness (work.py). The cases every suite holds
(contract v24's replacement and template catalogue, v26's event group) are
the SDK's.
"""

from __future__ import annotations

import itertools
from collections.abc import Awaitable, Callable
from pathlib import Path

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles.data.testing import feed_delay
from meridian.suites import ANSWERED_BY_SDK, Recorder, run, suite

from truefx.synthetic import Stated, Synthetic

from conftest import FORMING_NS, INSTANCE, LATER_NS, Records, recorder, want, work_on

Producer = Callable[[Recorder], Awaitable[None]]

NEVER_ABOUT = {
    "a crypto asset's price": "TrueFX quotes currency pairs: no token",
    "prices on a venue": "TrueFX's rates are indicative, from Integral's network: no venue's",
    "a security's price": "TrueFX quotes currency pairs: no security another source named",
    "trades": "nothing trades on TrueFX: its rates are indicative, so it states no trades",
    "calendars": "FX quotes need no settlement calendar: rates recorded as TrueFX states them",
    "settlement dates": "FX quotes need no settlement date: rates recorded as TrueFX states them",
    # Contract v23: an event contract's outcome.
    "outcomes": "TrueFX quotes currency pairs: no event contract, so no outcome",
    "disputed outcomes": "TrueFX quotes currency pairs: no event contract, so no outcome disputed",
    # Contract v27: the lake's rates slice.
    "rates": (
        "TrueFX quotes currency pairs, recorded as prices and quotes: no reference rate's "
        "fixing, curve or index level"
    ),
    # Contract v28 (ruling 602).
    "option chains": "TrueFX quotes currency pairs: no option chain",
    "filings": "TrueFX quotes currency pairs: no company's filings",
    "holdings": "TrueFX quotes currency pairs: no holdings report",
    "corporate actions": "TrueFX quotes currency pairs: no declared dividend",
    "ratings": "TrueFX quotes currency pairs: no rating",
}
NOT_PRESENTED: dict[str, str] = {
    case.name: NEVER_ABOUT[case.about] for case in suite("data").cases if case.about in NEVER_ABOUT
} | {
    "a-quote-recorded": "TrueFX states its bid and offer with no size: a quote's sizes are unset",
    "a-one-sided-quote": "TrueFX states both its bid and its offer on every rate it quotes",
    # Contract v27: the case is about trades.
    "queries-the-lake-within-bounds": "it records no trades",
    # Contract v28 (about quotes, ruling 602), named through a table: meridian
    # 0.1.52's check holds contract v27's suites.
    **{
        case: "TrueFX's rates are polled and number no message: no sequence to repeat or skip"
        for case in ("a-duplicate-is-recorded-suspicious", "rows-after-a-gap-are-suspicious")
    },
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

    async def heartbeat(lake: Recorder) -> None:
        # An authenticated session, every step of the feed answered and the
        # live dataset kept current for a standing want; then a poll a second
        # later answered with nothing moved, TrueFX's heartbeat: no quote
        # sent, the live dataset's liveness recorded at that poll.
        Records().answering(lake)
        feed = Synthetic()
        work = work_on(lake, fresh(), username="someone", synthetic=feed)
        ticks = itertools.count(LATER_NS, 1_000_000_000)
        work.clock_ns = work.client.clock_ns = lambda: next(ticks)
        while feed.at < len(feed.feed):
            await work.poll_once()
        lake.answer(
            "ObservationsWanted",
            lambda _: want("WNT-4", "live", ["LCL-EUR"], data_type="meridian.v1.Quote",
                           standing=True),
        )  # fmt: skip
        await lake.receive(observations_wanted=work.on_want)
        await work.keep_live()
        quotes = len(lake.on("RecordQuotes"))
        assert await work.poll_once() == 0
        await work.keep_live()
        assert len(lake.on("RecordQuotes")) == quotes

    async def kept_live(lake: Recorder, feed: Synthetic, latency: object = None) -> None:
        # A standing want of the euro's quote, kept current from TrueFX's
        # polls: each row recorded unasked, aged and judged at the edge.
        Records().answering(lake)
        work = work_on(lake, fresh(), username="someone", synthetic=feed)
        work.latency = latency
        await work.poll_once()
        lake.answer(
            "ObservationsWanted",
            lambda _: want("WNT-5", "live", ["LCL-EUR"], data_type="meridian.v1.Quote",
                           standing=True),
        )  # fmt: skip
        await lake.receive(observations_wanted=work.on_want)
        await work.keep_live()

    async def delayed(lake: Recorder, latency: object) -> None:
        # Contract v28 (ruling 518): the quotes' age at the edge, reported.
        await kept_live(lake, Synthetic(), latency)

    async def crossed(lake: Recorder) -> None:
        # Contract v28 (ruling 424): the euro quoted with its bid above its
        # offer, recorded invalid by the edge's checks.
        euro = Stated("EUR/USD", "1791547200003", "1.16440", "1.16434", "1.16495", "1.16359",
                      "1.16440")  # fmt: skip
        await kept_live(lake, Synthetic(feed=[[euro]]))

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
        "records-a-datasets-liveness": heartbeat,
        "reports-its-feed-delay": feed_delay(delayed),
        "a-crossed-quote-is-recorded-invalid": crossed,
    }


def test_every_case_of_the_data_suite_is_mapped_or_not_presented(tmp_path: Path) -> None:
    report = run("data", producers(tmp_path), not_presented=NOT_PRESENTED, instance_id=INSTANCE)
    assert report.passed, report.failures
    assert sorted(report.not_presented) == sorted(NOT_PRESENTED)
    # Contract v28: the feed delay and a crossed quote too.
    assert len(report.passed_cases) == 13 + len(ANSWERED_BY_SDK)
    assert "records-a-datasets-liveness" in report.passed_cases
    assert report.answered_by_sdk == list(ANSWERED_BY_SDK)


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
