"""TrueFX's FX rates as an Open Meridian data plugin.

It connects to the sidecar it is launched beside, declaring its catalogue,
its storage and its settings (declaration.py) and its pages (page.py), and
serves them. Once the settings have said where to answer from, it polls
TrueFX once a second, building each pair's day from the ticks; hears what
the lake wants of it and records it; keeps each standing want current; and
records each day as it closes (work.py), until stopped. Everything goes
through the sidecar; nothing but TrueFX's API is called, and with sample
data not even that (synthetic.py).

It holds nothing it cannot lose: TrueFX's raw responses, the pair map, the
days being built and the history files a person put there are in the
storage the deployment grants it (decisions/028), sample data's apart under
`synthetic/`; a restart reads them back and hears again what the lake wants.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import meridian

from . import raw
from .client import TrueFX, https
from .days import DayBook
from .declaration import DECLARATION, SAMPLE_DATA, USERNAME
from .history import FOLDER, History
from .page import TITLE, figures_now, hold, pages
from .pairs import PairMap
from .raw import RawStore, storage_root, tend
from .synthetic import HISTORY, Synthetic, copy_history
from .work import Work, cancelled

log = logging.getLogger("truefx")


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


def built(plugin: meridian.Plugin, store: RawStore, sample_data: bool, username: str) -> Work:
    client, root, history = source(store, sample_data, username)
    pairs = PairMap(root / "pairs.json")
    pairs.load()
    history.refresh()
    return Work(plugin, client, pairs, DayBook(root), history)


async def watch_settings(
    plugin: meridian.Plugin, work: Work, store: RawStore, configured: asyncio.Event
) -> None:
    """Each delivery of the settings: the source switched where sample data
    changed, the username given to the session, and each day's raw responses
    past their window moved."""
    while True:
        try:
            async for delivered in plugin.settings():
                await apply(plugin, work, store, delivered.values)
                configured.set()
        except Exception as failed:  # noqa: BLE001 - the stream broke: said, and watched again
            log.warning("the settings' stream broke, watching again: %s", failed)
        await asyncio.sleep(2)


async def apply(
    plugin: meridian.Plugin, work: Work, store: RawStore, values: Mapping[str, object]
) -> None:
    sample = values.get(SAMPLE_DATA) is True
    named = values.get(USERNAME)
    username = named.strip() if isinstance(named, str) else ""
    log.info("settings delivered: sample data %s, a username %s", sample,
             "set" if username else "not set")  # fmt: skip
    if sample != (work.client.mode != "live"):
        fresh = built(plugin, store, sample, username)
        work.use(fresh.client, fresh.pairs, fresh.book, fresh.history)
        log.info("answering from %s", work.client.mode)
    work.client.use_username(username)
    window = values.get(f"{raw.KIND}_window_days")
    past = values.get(f"{raw.KIND}_past_window")
    await tend(
        plugin,
        store,
        window if isinstance(window, int) else raw.WINDOW_DAYS,
        past if isinstance(past, str) else "kept",
        datetime.now(UTC).date(),
    )


async def hear_wants(plugin: meridian.Plugin, work: Work, configured: asyncio.Event) -> None:
    """What the lake wants, once the settings have said where to answer from."""
    await configured.wait()
    await plugin.receive(observations_wanted=work.on_want, want_withdrawn=work.on_withdrawn)


async def keep_current(work: Work, configured: asyncio.Event) -> None:
    await configured.wait()
    await work.keep_current()


async def report_health(plugin: meridian.Plugin, work: Work) -> None:
    """Each minute: its datasets' licences read again (contract v20), and
    on the heartbeat whether TrueFX answers, with the data role's figures."""
    while True:
        try:
            await work.read_licences()
        except meridian.MeridianError as failed:
            log.warning("licences not read: %s", failed)
        health = work.client.health
        healthy = health.last_ok_ns >= health.last_failed_ns
        detail = "TrueFX answers" if healthy else health.last_error
        try:
            await plugin.report(healthy=healthy, detail=detail[:200], figures=figures_now())
        except (meridian.MeridianError, ValueError) as failed:
            log.warning("health not reported: %s", failed)
        await asyncio.sleep(60)


def _said(task: asyncio.Task[None]) -> None:
    """A task that stopped, said with why, and the plugin stopped with it: a
    restart starts it again."""
    if not task.cancelled() and task.exception() is not None:
        log.error("stopped: %r", task.exception(), exc_info=task.exception())
        os._exit(1)


async def run() -> None:
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for stop in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(stop, stopped.set)

    port = int(os.environ.get("TRUEFX_PAGE_PORT", "8000"))
    async with await meridian.connect(
        interface=meridian.Interface(port=port, title=TITLE, pages=pages),
        declaration=DECLARATION,
    ) as plugin:
        log.info("registered as %s, roles %s", plugin.identity.instance_id, plugin.identity.roles)
        store = RawStore(storage_root())
        work = built(plugin, store, sample_data=False, username="")
        hold(work)
        served = pages.serve(plugin, port)
        configured = asyncio.Event()
        tasks = [
            asyncio.create_task(watch_settings(plugin, work, store, configured)),
            asyncio.create_task(hear_wants(plugin, work, configured)),
            asyncio.create_task(keep_current(work, configured)),
            asyncio.create_task(report_health(plugin, work)),
        ]
        for task in tasks:
            task.add_done_callback(_said)
        await stopped.wait()
        log.info("stopping")
        for task in tasks:
            await cancelled(task)
        work.book.save()
        served.shutdown()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
