"""What the tests share: a deployment's records standing in for the master,
and the plugin's work on the synthetic feed against the SDK's `Recorder`.

The deployment holds a cash instrument per currency, `LCL-<code>`, each
carrying its `iso4217` identifier; and a custodian's record of the euro,
`LCL-custodian-eur`, carrying the custodian's symbol and the euro's ISO code
(another source's record of a currency, which the plugin names by reading
it, W3.6). An ISO code in `missing` resolves to nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.suites import Recorder

from truefx.client import TrueFX
from truefx.days import DayBook
from truefx.history import History
from truefx.pairs import PairMap
from truefx.raw import RawStore
from truefx.synthetic import HISTORY, Synthetic, copy_history
from truefx.work import Work

INSTANCE = "truefx"


def ns(text: str) -> int:
    """An ISO 8601 instant, UTC, in nanoseconds."""
    moment = datetime.fromisoformat(text).replace(tzinfo=UTC)
    return int(moment.timestamp()) * 1_000_000_000 + moment.microsecond * 1_000


#: 12:00 New York on Friday 9 October 2026: business date 9 October, forming.
FORMING_NS = ns("2026-10-09T16:00:00")
#: 20:00 New York on Monday 12 October 2026: business date 13 October.
LATER_NS = ns("2026-10-13T00:00:00")


@dataclass
class Records:
    """The deployment's records, answering the recorder's resolves."""

    missing: set[str] = field(default_factory=set)
    ambiguous: set[str] = field(default_factory=set)

    def resolve(self, params: Any) -> Any:
        code = next((i.value for i in params.identifiers if i.scheme == "iso4217"), "")
        if code in self.ambiguous:
            return ops.ResolveIdentifierResult(found=False, miss_reason=ops.MISS_REASON_AMBIGUOUS)
        if not code or code in self.missing:
            return ops.ResolveIdentifierResult(found=False, miss_reason=ops.MISS_REASON_NOT_FOUND)
        return ops.ResolveIdentifierResult(found=True, instrument_id=f"LCL-{code}")

    def record(self, params: Any) -> Any:
        subject = params.instrument_id
        if subject == "LCL-custodian-eur":
            identifiers = [
                ops.Identifier(scheme="symbol", value="EURO", source="custodian"),
                ops.Identifier(scheme="iso4217", value="EUR"),
            ]
        elif subject == "LCL-custodian-qqq":
            identifiers = [
                ops.Identifier(scheme="cusip", value="46090E103"),
                ops.Identifier(scheme="symbol", value="QQQ", source="custodian"),
            ]
        elif subject.startswith("LCL-") and len(subject) == 7:
            identifiers = [ops.Identifier(scheme="iso4217", value=subject[4:])]
        else:
            return ops.ResolveInstrumentResult(found=False)
        return ops.ResolveInstrumentResult(
            found=True, instrument=ops.InstrumentRecord(instrument_id=subject,
                                                        identifiers=identifiers)
        )  # fmt: skip

    def answering(self, recorder: Recorder) -> Recorder:
        recorder.answer("ResolveIdentifier", self.resolve)
        recorder.answer("ResolveInstrument", self.record)
        return recorder


def work_on(
    recorder: Any,
    root: Path,
    now_ns: int = LATER_NS,
    username: str = "",
    synthetic: Synthetic | None = None,
) -> Work:
    """The plugin's work on the synthetic feed and its history files, its
    storage under `root`, its clock stopped at `now_ns`."""
    clock = lambda: now_ns  # noqa: E731
    store = RawStore(root)
    copy_history(root)
    client = TrueFX(store, synthetic or Synthetic(), "synthetic", username, clock_ns=clock)
    history = History(root / HISTORY, f"{HISTORY}/", root / "synthetic" / "history-days")
    history.refresh()
    return Work(recorder, client, PairMap(root / "synthetic" / "pairs.json"),
                DayBook(root / "synthetic"), history, clock_ns=clock)  # fmt: skip


def recorder(records: Records | None = None) -> Recorder:
    return (records or Records()).answering(Recorder(INSTANCE))


def want(
    want_id: str,
    key: str,
    subjects: list[str],
    *,
    day: str = "",
    data_type: str = "meridian.v1.Price",
    kinds: tuple[int, ...] = (),
    standing: bool = False,
) -> ops.ObservationsWantedEvent:
    return ops.ObservationsWantedEvent(
        want_id=want_id,
        dataset=f"{INSTANCE}:{key}",
        data_type=data_type,
        subjects=[ops.SubjectRef(entity_id=s) for s in subjects],
        kinds=[ops.PriceKind.Name(k) for k in kinds],
        business_date=day,
        standing=standing,
    )
