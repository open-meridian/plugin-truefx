"""The declaration: the catalogue declared from code, as registration and
`meridian plugin upload` read it; and the settings in the data role's order."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from truefx.declaration import DECLARATION
from truefx.declared import CATALOGUE, Config

ROOT = Path(__file__).resolve().parents[1]


def test_two_datasets_daily_and_live_on_new_yorks_day_ending_at_17_00() -> None:
    assert [d.key for d in CATALOGUE] == ["daily", "live"]
    for dataset in CATALOGUE:
        assert (dataset.vendor, dataset.day_time_zone, dataset.day_end_minute) == (
            "TrueFX", "America/New_York", 1020)  # fmt: skip
        assert dataset.venue_id == "", "TrueFX's rates are indicative: no venue's"
    daily, live = CATALOGUE
    assert list(daily.data_types) == ["meridian.v1.Price", "meridian.v1.Bar"]
    assert list(live.data_types) == ["meridian.v1.Price", "meridian.v1.Quote"]
    assert daily.licence_default and daily.licence_default.kept
    assert live.licence_default and live.licence_default.retention_days == 2


def test_neither_dataset_declares_a_delay() -> None:
    # Contract v27: TrueFX states its rates live, and the daily dataset is
    # built from the same polls, so both are declared real time.
    for dataset in CATALOGUE:
        assert dataset.declared_delay_ns == 0
        assert dataset._to_json()["declared_delay_ns"] == 0


def test_the_username_secret_and_optional_then_sample_data() -> None:
    declared = cast(Any, Config).declared()
    assert [s.name for s in declared] == ["username", "sample_data"]
    username, sample = declared
    assert (username.secret, username.required, username.label) == (
        True, False, "TrueFX username")  # fmt: skip
    assert (sample.developer, sample.default) == (True, False)
    assert DECLARATION.storage is not None


def test_upload_reads_the_same_declaration() -> None:
    printed = subprocess.run(
        [str(Path(sys.executable).parent / "meridian-declaration"),
         "truefx.declaration:DECLARATION"],
        capture_output=True, text=True, check=True, cwd=ROOT,
    )  # fmt: skip
    datasets = json.loads(printed.stdout)["catalogue"]["datasets"]
    assert [d["key"] for d in datasets] == ["daily", "live"]
    assert [d["modes"] for d in datasets] == [["pull", "push"], ["pull", "stream"]]
