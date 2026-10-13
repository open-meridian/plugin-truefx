"""The plugin's pages, under Manage: the data role's Connection and Datasets
(spec/plugin-pages-follow-their-role), built on `meridian.roles.data`.

A data plugin shows no market data: no rate, quote or bar is on either page;
viewing prices is for the reading roles. Both pages are the role's, in its
order, their sections, rows, labels and "not set up yet" states the role
template's; TrueFX's nuance is added only at the template's blocks:

- **Connection** (`/`, `read_connection`): "Key" -- the mode (Live, or
  Sample data), the TrueFX username set or not (never its value), what
  TrueFX serves this session (27 pairs authenticated, 10 without), and
  TrueFX's rows: the session, authenticated or not, and when it was opened;
  "Limits and use" -- TrueFX states no limit, and the plugin polls once a
  second -- its calls, the last call and the last error; and "Stream":
  TrueFX's API is polled, so "Does not stream".
- **Datasets** (`/datasets`, `read_datasets`): "Served" -- each dataset of
  its catalogue, its data, how its rows arrive, its day, its default terms
  and whether a deployment admin has licensed it (contract v20), and what it
  recorded and declined and when it last recorded -- "Wants", each want
  heard and each standing want it keeps current, searched and paged by the
  kit's `om-pager` -- "Subjects" -- then a section under TrueFX's name: the
  pairs whose currencies resolved, the currencies not resolved, the days
  built from its polls, and the history files held and the months they
  cover.

Each page declares the record it renders (`answers=`), the role's record
extended with TrueFX's fields, so each is also a read tool on the
deployment's MCP surface answering the same record under the role's names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import meridian
from meridian import Figure
from meridian.roles import data
from meridian.v1 import sidecar_pb2

from .declaration import CATALOGUE, DAILY, LIVE, VENDOR
from .work import POLL_SECONDS, Work

TITLE = VENDOR
#: The kit the pages are built against.
KIT = "0.12.0"

pages = meridian.Pages(TITLE, templates=Path(__file__).parent / "templates", kit=KIT)


class _Held:
    work: Work | None = None


HELD = _Held()


def hold(work: Work) -> None:
    """The work the pages show."""
    HELD.work = work


def _when(at_ns: int) -> str:
    """A time as the role's records carry it: ISO 8601, to the second, UTC."""
    if not at_ns:
        return ""
    return datetime.fromtimestamp(at_ns // 1_000_000_000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _entitled(work: Work | None) -> str:
    if work is None or not work.client.authenticated:
        return "10 pairs, unauthenticated"
    return "27 pairs, authenticated"


# ── Connection ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Connection(data.ConnectionRead):
    """The role's Connection, and TrueFX's: its session, authenticated or
    not, when it was opened and how often, its address and what did not
    read."""

    vendor: str = VENDOR
    address: str = ""
    session: str = ""
    session_opened_at: str = ""
    sessions_opened: int = 0
    healthy: bool = False
    failures: int = 0
    not_read: int = 0


def connection_now() -> Connection:
    work = HELD.work
    limit = (
        f"TrueFX states no limit. This plugin: one poll each {POLL_SECONDS:g} second, "
        "and a session request when a session is lost"
    )
    if work is None:
        return Connection(mode="Live", limit=limit, entitled_at_vendor=_entitled(None))
    client = work.client
    health = client.health
    healthy = health.last_ok_ns >= health.last_failed_ns and (
        health.last_ok_ns > 0 or health.calls == 0
    )
    return Connection(
        mode="Live" if client.mode == "live" else "Sample data",
        credentials=[data.Credential("TrueFX username", client.authenticated)],
        entitled_at_vendor=_entitled(work),
        limit=limit,
        calls=health.calls,
        last_call_at=_when(max(health.last_ok_ns, health.last_failed_ns)),
        last_error=health.last_error,
        sessions=None,
        address=client.address,
        session="Authenticated" if client.authenticated else "Unauthenticated",
        session_opened_at=_when(health.session_opened_ns),
        sessions_opened=health.sessions_opened,
        healthy=healthy,
        failures=health.failures,
        not_read=health.unread,
    )


@pages.page("/", "Connection", levels="admin", answers=Connection, name="read_connection")
def connection(request: meridian.Request) -> meridian.Response:
    """How the plugin reaches TrueFX: the mode, the username set or not,
    what TrueFX serves the session and the session; TrueFX's limit and what
    the plugin spends, its calls, the last call and the last error."""
    return pages.answer("connection.html", connection_now())


# ── Datasets ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Want(data.Want):
    """The role's want, with its ID and whether it is kept current."""

    want_id: str = ""
    kept_current: bool = False


@dataclass(frozen=True)
class Datasets(data.DatasetsRead):
    """The role's Datasets, and TrueFX's pairs, days and history files."""

    standing_wants: int = 0
    pairs_served: int = 0
    pairs_resolved: int = 0
    currencies_not_resolved: list[str] = field(default_factory=list)
    days_built: int = 0
    history_files: int = 0
    history_months: list[str] = field(default_factory=list)
    history_not_read: int = 0
    restated: int = 0
    unchanged: int = 0


def _terms(licence: meridian.DatasetLicence | None) -> str:
    if licence is None:
        return ""
    said = ["kept" if licence.kept else "served, not kept"]
    if licence.retention_days:
        said.append(f"{licence.retention_days} days")
    said.append("display" if licence.display else "no display")
    if licence.personal_use:
        said.append("one person's")
    return ", ".join(said)


def _arrives(mode: object) -> str:
    if isinstance(mode, int):
        named = str(sidecar_pb2.ObservationMode.Name(mode))
        return named.removeprefix("OBSERVATION_MODE_").lower()
    return str(mode)


def _state(kept_current: bool, standing: bool) -> str:
    return "Kept current" if kept_current else "Withdrawn" if standing else "Answered"


def datasets_now() -> Datasets:
    work = HELD.work
    instance = work.plugin.identity.instance_id if work else "truefx"
    served = []
    for declared in CATALOGUE:
        name = f"{instance}:{declared.key}"
        sent = work.sent_to(declared.key) if work else None
        served.append(
            data.Served(
                dataset=name,
                data=", ".join(t.removeprefix("meridian.v1.") for t in declared.data_types),
                arrives=", ".join(_arrives(m) for m in declared.modes),
                day=f"{declared.day_time_zone}, ends {declared.day_end_minute // 60:02d}:"
                f"{declared.day_end_minute % 60:02d}",
                default_terms=_terms(declared.licence_default),
                entitled_at_vendor=_entitled(work),
                recorded=sent.recorded if sent else 0,
                declined=sent.declined if sent else 0,
                last_recorded=_when(sent.last_ns) if sent else "",
                licensed=work is not None and name in work.licensed,
            )
        )
    if work is None:
        return Datasets(served=served)
    standing = set(work.standing)
    wants: dict[str, Want] = {}
    for heard in work.heard:  # newest first: a want heard again is one row, as last heard
        if heard.want_id in wants:
            continue
        kept = heard.want_id in standing
        wants[heard.want_id] = Want(
            dataset=heard.dataset,
            asked=heard.asked,
            subjects=heard.subjects,
            recorded=heard.recorded,
            declined=heard.declined,
            state=_state(kept, heard.standing),
            want_id=heard.want_id,
            kept_current=kept,
        )
    kept_first: list[data.Want] = sorted(wants.values(), key=lambda w: w.state != "Kept current")
    months = sorted(
        {f"{m.pair} {m.month[0]:04d}-{m.month[1]:02d}" for m in work.history.months.values()}
    )
    return Datasets(
        served=served,
        wants=kept_first,
        reads_instruments=work.reads_instruments,
        standing_wants=len(standing),
        pairs_served=len(work.client.pairs),
        pairs_resolved=sum(1 for p in work.client.pairs if work.pairs.resolved(p)),
        currencies_not_resolved=sorted(work.pairs.missing),
        days_built=len(work.book.held_days()),
        history_files=len(work.history.months),
        history_months=months,
        history_not_read=work.history.unread(),
        restated=work.counts.restated,
        unchanged=work.counts.unchanged,
    )


@pages.page("/datasets", "Datasets", levels="admin", answers=Datasets, name="read_datasets")
def datasets(request: meridian.Request) -> meridian.Response:
    """What the plugin serves the lake: each dataset of its catalogue and
    whether it is licensed, what it recorded and declined; the wants it
    heard and the standing wants it keeps current; whether it may read an
    instrument's record; and its pairs, days and history files."""
    return pages.answer("datasets.html", datasets_now(), vendor=VENDOR)


# ── Figures ─────────────────────────────────────────────────────────────────


def figures_now() -> list[Figure]:
    """The data role's figures on the Summary, in its order: Connection,
    Entitled at the vendor, Stream and Last recorded. TrueFX states no rate
    limit to measure against, so Rate use is left out."""
    work = HELD.work
    if work is None:
        return data.figures(connection="Answering")
    said = connection_now()
    if said.mode == "Sample data":
        answering: str | Figure = "Sample data"
    elif said.healthy:
        answering = "Answering"
    else:
        answering = Figure("", "Not answering", state="error", why=said.last_error[:200] or None)
    last = max((work.sent_to(key).last_ns for key in (DAILY, LIVE)), default=0)
    return data.figures(
        connection=answering,
        entitled_at_vendor=f"{len(CATALOGUE)} of {len(CATALOGUE)} datasets",
        stream="Does not stream",
        last_recorded=datetime.fromtimestamp(last // 1_000_000_000, tz=UTC) if last else None,
    )
