"""The pages, Connection and Datasets, and their read tools.

Asked in-process as the sidecar would ask them (`meridian.testing`), after
the plugin has polled the synthetic feed and answered wants: each page is
served under Manage alone, shows no price, fits its rows on one line each,
holds the data role's sections in the role's order, and its tool answers
what the page shows under the role's names; the username is said set or not,
never shown; and the role's figures come in the role's order.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from meridian.operations import as_decimal
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.suites import Recorder
from meridian.testing import PageClient

from truefx.page import figures_now, hold, pages
from truefx.work import Work

from conftest import INSTANCE, recorder, want, work_on


def worked(tmp_path: Path, username: str = "") -> tuple[Work, Recorder]:
    lake = recorder()
    work = work_on(lake, tmp_path, username=username)
    lake.answer(
        "ObservationsWanted",
        lambda _: [
            want("WNT-1", "daily", ["LCL-EUR"], day="2026-10-08", data_type=""),
            want("WNT-2", "live", ["LCL-USD"], data_type="", standing=True),
            want("WNT-3", "daily", ["LCL-JPY"], day="2026-10-08"),
        ],
    )
    asyncio.run(lake.receive(observations_wanted=work.on_want))
    asyncio.run(work.poll_once())
    work.licensed = frozenset({f"{INSTANCE}:daily"})
    hold(work)
    return work, lake


def text(path: str) -> str:
    answered = PageClient(pages, deployment_admin=True).get(path, "admin")
    assert answered.status == 200
    return answered.text


def test_each_page_is_served_under_manage_alone(tmp_path: Path) -> None:
    worked(tmp_path)
    served = {(r.page.path, r.level): r.response.status for r in PageClient(pages).every_page()}
    assert {path for path, _ in served} == {"/", "/datasets"}
    for (_, level), status in served.items():
        assert status == (200 if level == "admin" else 403), (level, status)


def test_no_page_shows_a_price(tmp_path: Path) -> None:
    _, lake = worked(tmp_path)
    amounts = {str(as_decimal(p.price.amount)) for s in lake.on("RecordPrices") for p in s.prices}
    assert amounts
    for path in ("/", "/datasets"):
        page = text(path)
        shown = [a for a in amounts if re.search(rf"(?<![\d.]){re.escape(a)}(?![\d.])", page)]
        assert not shown, (path, shown)


def test_every_table_is_one_line_rows_and_the_sections_in_the_roles_order(
    tmp_path: Path,
) -> None:
    worked(tmp_path)
    connection, datasets = text("/"), text("/datasets")
    for page in (connection, datasets):
        tables = re.findall(r"<table[^>]*>", page)
        assert tables and all('class="one-line"' in t for t in tables)
    assert re.findall(r"<h2>([^<]*)</h2>", connection) == ["Key", "Limits and use", "Stream"]
    assert re.findall(r"<h2>([^<]*)</h2>", datasets) == ["Served", "Wants", "Subjects", "TrueFX"]
    assert '<om-pager search="Search wants">' in datasets


def test_connection_says_the_session_and_never_the_username(tmp_path: Path) -> None:
    worked(tmp_path, username="jsTrader")
    page = text("/")
    assert "TrueFX username: set" in page and "jsTrader" not in page
    assert "Authenticated" in page and "27 pairs, authenticated" in page
    assert "Does not stream" in page and "Sample data" in page
    answered = PageClient(pages).call_tool("read_connection")
    assert answered.outcome == "unchanged"
    data = answered.data
    assert data["credentials"] == [{"label": "TrueFX username", "set": True}]
    assert data["session"] == "Authenticated" and data["sessions"] is None
    assert data["mode"] == "Sample data" and data["sessions_opened"] == 1
    assert "jsTrader" not in str(data)


def test_without_a_username_the_ten_pairs_trueFX_serves_anyone(tmp_path: Path) -> None:
    worked(tmp_path)
    page = text("/")
    assert "TrueFX username: not set" in page and "10 pairs, unauthenticated" in page
    assert "The ten pairs TrueFX serves anyone." in page


def test_datasets_answers_what_the_page_shows(tmp_path: Path) -> None:
    worked(tmp_path)
    page = text("/datasets")
    data = PageClient(pages).call_tool("read_datasets").data
    assert [s["dataset"] for s in data["served"]] == [f"{INSTANCE}:daily", f"{INSTANCE}:live"]
    assert [s["licensed"] for s in data["served"]] == [True, False]
    assert data["served"][0]["day"] == "America/New_York, ends 17:00"
    assert data["pairs_served"] == 10 and data["pairs_resolved"] == 10
    assert data["history_months"] == ["EURUSD 2026-10", "GBPUSD 2026-10", "USDJPY 2026-10"]
    assert data["standing_wants"] == 1
    assert {w["want_id"]: w["state"] for w in data["wants"]} == {
        "WNT-1": "Answered", "WNT-2": "Kept current", "WNT-3": "Answered"}  # fmt: skip
    assert "10 of 10 pairs with both currencies resolved" in page
    assert "Licensed" in page and "Not licensed yet" in page
    assert "EURUSD 2026-10, GBPUSD 2026-10, USDJPY 2026-10" in page


def test_the_roles_figures_in_its_order(tmp_path: Path) -> None:
    worked(tmp_path)
    figures = figures_now()
    assert [f.label for f in figures] == [
        "Connection", "Entitled at the vendor", "Stream", "Last recorded"]  # fmt: skip
    assert figures[0].value == "Sample data" and figures[2].value == "Does not stream"


def test_a_want_answered_is_listed_with_what_it_declined(tmp_path: Path) -> None:
    work, lake = worked(tmp_path)
    declined = {d.want_id: d.reason for d in lake.on("DeclineWant")}
    assert declined == {"WNT-3": ops.UNANSWERED_REASON_NOT_COVERED}
    [heard] = [h for h in work.heard if h.want_id == "WNT-3"]
    assert (heard.subjects, heard.declined) == (1, 1)
