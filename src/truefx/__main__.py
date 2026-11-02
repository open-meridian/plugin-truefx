"""TrueFX's FX rates as an Open Meridian data plugin.

It runs its data role class, `Lake` (work.py's `Work`, with its lifecycle
here), with `meridian.run` on the sidecar it is launched beside, declaring
its whole declaration (declaration.py): its catalogue, its storage, its
settings, its pages (page.py) and its documentation. `meridian.run` serves
the pages, delivers the settings -- the first before anything is heard --
hands it what the lake wants, and sets the data role's figures on each
heartbeat. Once the settings have said where to answer from, it polls
TrueFX once a second, building each pair's day from the ticks; records what
the lake wants; keeps each standing want current; and records each day as
it closes (work.py), until stopped. Everything goes through the sidecar;
nothing but TrueFX's API is called, and with sample data not even that
(synthetic.py).

It holds nothing it cannot lose: TrueFX's raw responses, the pair map, the
days being built and the history files a person put there are in the
storage the deployment grants it (decisions/028), sample data's apart under
`synthetic/`; a restart reads them back and hears again what the lake wants.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import meridian
from meridian.roles import Latency

from . import raw
from .client import TrueFX, https
from .days import DayBook
from .declaration import DECLARATION, PORT
from .declared import SAMPLE_DATA, USERNAME
from .history import FOLDER, History
from .page import figures_now, hold, pages
from .pairs import PairMap
from .raw import RawStore, storage_root, tend
from .synthetic import HISTORY, Synthetic, copy_history
from .work import Work

log = logging.getLogger("truefx")

#: How often its datasets' licences are read again and whether TrueFX
#: answers is said on its health.
HEALTH_EVERY_SECONDS = 60


def source(store: RawStore, sample_data: bool, username: str) -> tuple[TrueFX, Path, History]:
    """TrueFX itself, or with sample data the synthetic feed; the root its
    pair map and days are kept under, and its history files."""
    root = store.root
    if not sample_data:
        client = TrueFX(store, https, "live", username)
        return client, root, History(root / FOLDER, f"{FOLDER}/", root / "history-days")
    mode_root = root / "synthetic"
    copy_history(root)
    client = TrueFX(store, Synthetic(), "synthetic", username)
    return client, mode_root, History(root / HISTORY, f"{HISTORY}/", mode_root / "history-days")


def built(
    store: RawStore, sample_data: bool, username: str
) -> tuple[TrueFX, PairMap, DayBook, History]:
    """What the work answers from: the source, its pair map, its days and
    its history, each read back from storage."""
    client, root, history = source(store, sample_data, username)
    pairs = PairMap(root / "pairs.json")
    pairs.load()
    history.refresh()
    return client, pairs, DayBook(root), history


@dataclass
class Lake(Work):
    """The data role's class with its lifecycle (open-meridian 0.35, rulings
    1004, 1005, 1009 to 1023): `meridian.run` delivers each settings to
    `on_settings` -- the first before anything is heard -- starts `run`,
    again after a backoff should it fail, and calls `on_stop` as it stops."""

    store: RawStore | None = None

    async def on_settings(self, delivered: Any) -> None:
        """Each delivery of the settings: the source switched where sample
        data changed, the username given to the session, and each day's raw
        responses past their window moved."""
        await self.apply(delivered.values)

    async def apply(self, values: Mapping[str, object]) -> None:
        sample = values.get(SAMPLE_DATA) is True
        named = values.get(USERNAME)
        username = named.strip() if isinstance(named, str) else ""
        log.info("settings delivered: sample data %s, a username %s", sample,
                 "set" if username else "not set")  # fmt: skip
        assert self.store is not None
        if sample != (self.client.mode != "live"):
            self.use(*built(self.store, sample, username))
            log.info("answering from %s", self.client.mode)
        self.client.use_username(username)
        window = values.get(f"{raw.KIND}_window_days")
        past = values.get(f"{raw.KIND}_past_window")
        await tend(
            self.plugin,
            self.store,
            window if isinstance(window, int) else raw.WINDOW_DAYS,
            past if isinstance(past, str) else "kept",
            datetime.now(UTC).date(),
        )

    async def run(self) -> None:
        """TrueFX polled once a second and the standing wants kept current,
        its health said each minute, and the feed delay reported (contract
        v28, ReportLatency)."""
        work = [self.keep_current(), self._health()]
        if self.latency is not None:
            work.append(self.latency.run())
        await asyncio.gather(*work)

    async def on_stop(self) -> None:
        self.book.save()

    async def _health(self) -> None:
        """Each minute: its datasets' licences read again (contract v20), and
        on its health whether TrueFX answers."""
        while True:
            try:
                await self.read_licences()
            except meridian.MeridianError as failed:
                log.warning("licences not read: %s", failed)
            health = self.client.health
            healthy = health.last_ok_ns >= health.last_failed_ns
            detail = "TrueFX answers" if healthy else health.last_error
            try:
                await self.plugin.report(healthy=healthy, detail=detail[:200])
            except (meridian.MeridianError, ValueError) as failed:
                log.warning("health not reported: %s", failed)
            await asyncio.sleep(HEALTH_EVERY_SECONDS)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    store = RawStore(storage_root())
    lake = Lake(*built(store, sample_data=False, username=""), store=store)
    # Contract v28 (ruling 518): each row recorded unasked or for a standing
    # want has its age at the edge recorded, reported every 10 seconds
    # (ReportLatency).
    lake.latency = Latency(lake)
    hold(lake)
    # The version's whole declaration (declaration.py): its settings, its
    # catalogue and storage, its pages with the levels each serves and their
    # tools, and its documentation. A version registers exactly what it was
    # uploaded with (contract v25).
    meridian.run(
        declaration=DECLARATION,
        roles=[lake],
        pages=pages,
        port=PORT,
        on_settings=lake.on_settings,
        figures=figures_now,
    )


if __name__ == "__main__":
    main()
