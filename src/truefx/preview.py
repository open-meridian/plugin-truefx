"""The pages as a deployment admin would see them, on the synthetic feed,
each printed as one HTML file: for looking at them without a deployment.

    python -m truefx.preview connection > preview/connection.html
    python -m truefx.preview datasets > preview/datasets.html
    python -m truefx.preview datasets-empty > preview/datasets-empty.html

The page links the kit where the dashboard serves it, /.meridian/ui/<version>/,
so serve it beside the kit to see it styled; opened on its own it is the
page without the kit, unstyled, which works too.

There is no sidecar here: the SDK's `Recorder` answers as one would, each
currency resolving to a cash instrument; TrueFX answers from the synthetic
feed; and the lake asks for a run of days and keeps two subjects current, so
the Datasets page has wants to page through. A deployment admin has licensed
the daily dataset and not the live one. `datasets-empty` is the page of a
plugin just started, before the lake has asked anything.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.suites import Recorder
from meridian.testing import PageClient

from .client import TrueFX
from .days import DayBook
from .history import History
from .page import hold, pages
from .pairs import PairMap
from .raw import RawStore
from .synthetic import HISTORY, Synthetic, copy_history
from .work import Work

#: The preview's clock: 2026-10-13 00:00 UTC.
NOW_NS = 1_791_849_600 * 1_000_000_000


def _resolved(params: Any) -> Any:
    code = next((i.value for i in params.identifiers if i.scheme == "iso4217"), "")
    return ops.ResolveIdentifierResult(found=True, instrument_id=f"LCL-{code}")


def _delivering(want: ops.ObservationsWantedEvent) -> Callable[[Any], Any]:
    return lambda _: want


def _work(lake: Recorder) -> Work:
    root = Path(tempfile.mkdtemp(prefix="truefx-preview-"))
    copy_history(root)
    client = TrueFX(RawStore(root), Synthetic(), "synthetic", clock_ns=lambda: NOW_NS)
    history = History(root / HISTORY, f"{HISTORY}/")
    history.refresh()
    return Work(lake, client, PairMap(), DayBook(), history, clock_ns=lambda: NOW_NS)


async def _worked() -> Work:
    lake = Recorder("truefx")
    lake.answer("ResolveIdentifier", _resolved)
    work = _work(lake)
    for _ in range(3):
        await work.poll_once()
    await work.push_closed()
    for n in range(24):
        day = date(2026, 10, 9) - timedelta(days=n % 7)
        want = ops.ObservationsWantedEvent(
            want_id=f"WNT-{n:04d}",
            dataset="truefx:daily",
            data_type="meridian.v1.Price",
            subjects=[ops.SubjectRef(entity_id="LCL-EUR" if n % 2 else "LCL-USD")],
            business_date=day.isoformat(),
        )
        lake.answer("ObservationsWanted", _delivering(want))
        await lake.receive(observations_wanted=work.on_want)
    for n, subject in enumerate(("LCL-EUR", "LCL-GBP")):
        want = ops.ObservationsWantedEvent(
            want_id=f"WNT-L{n}",
            dataset="truefx:live",
            data_type="meridian.v1.Quote",
            subjects=[ops.SubjectRef(entity_id=subject)],
            standing=True,
        )
        lake.answer("ObservationsWanted", _delivering(want))
        await lake.receive(observations_wanted=work.on_want)
    work.licensed = frozenset({work.dataset("daily")})
    return work


def main(argv: list[str]) -> int:
    page = argv[0] if argv else "connection"
    paths = {"connection": "/", "datasets": "/datasets", "datasets-empty": "/datasets"}
    if page not in paths:
        print(f"no page {page!r}: connection, datasets or datasets-empty", file=sys.stderr)
        return 2
    hold(_work(Recorder("truefx")) if page == "datasets-empty" else asyncio.run(_worked()))
    answered = PageClient(pages, deployment_admin=True).get(paths[page], "admin")
    sys.stdout.write(answered.text)
    return 0 if answered.status == 200 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
