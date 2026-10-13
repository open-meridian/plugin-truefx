"""TrueFX's monthly tick files, read into days: what they cover, every tick
in its day, and a line that does not read counted, never guessed."""

from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

from truefx.history import History, read_month
from truefx.pairs import BY_SYMBOL

EUR_USD, USD_JPY = BY_SYMBOL["EUR/USD"], BY_SYMBOL["USD/JPY"]

SEPTEMBER = """\
EUR/USD,20260930 21:05:00.000,1.10000,1.10002
EUR/USD,20260930 23:59:59.999,1.10100,1.10102
"""
OCTOBER = """\
EUR/USD,20261001 03:00:00.000,1.09900,1.09902
EUR/USD,20261001 20:59:59.500,1.09950,1.09954
not a line at all
EUR/USD,20261001 21:00:00.000,1.09960,1.09964
EUR/USD,20261002 20:00:00.000,abc,1.09964
"""


def test_a_month_is_read_into_days_every_tick_in_its_day(tmp_path: Path) -> None:
    path = tmp_path / "EURUSD-2026-10.csv"
    path.write_text(OCTOBER, encoding="utf-8")
    month = read_month(path, "history/")
    assert month is not None and month.pair == "EURUSD" and month.month == (2026, 10)
    assert [(b.day, b.ticks) for b in month.bars] == [(date(2026, 10, 1), 2),
                                                      (date(2026, 10, 2), 1)]  # fmt: skip
    assert month.unread == 2
    assert month.bars[0].raw_key == "history/EURUSD-2026-10.csv#1"


def test_a_day_is_covered_only_where_every_month_it_touches_is_held(tmp_path: Path) -> None:
    (tmp_path / "EURUSD-2026-10.csv").write_text(OCTOBER, encoding="utf-8")
    history = History(tmp_path)
    history.refresh()
    # 1 October began at 17:00 New York on 30 September: September's file.
    assert not history.covers(EUR_USD, date(2026, 10, 1))
    assert history.bar(EUR_USD, date(2026, 10, 1)) is None
    assert history.covers(EUR_USD, date(2026, 10, 2))
    assert not history.covers(USD_JPY, date(2026, 10, 2))
    (tmp_path / "EURUSD-2026-09.csv").write_text(SEPTEMBER, encoding="utf-8")
    history.refresh()
    bar = history.bar(EUR_USD, date(2026, 10, 1))
    assert bar is not None and bar.ticks == 4
    assert (str(bar.open), str(bar.close)) == ("1.10001", "1.09952")
    assert history.first_day(EUR_USD) == date(2026, 10, 1)


def test_a_zipped_month_reads_as_the_csv_it_holds(tmp_path: Path) -> None:
    with zipfile.ZipFile(tmp_path / "EURUSD-2026-10.zip", "w") as archive:
        archive.writestr("EURUSD-2026-10.csv", OCTOBER)
    history = History(tmp_path)
    history.refresh()
    bar = history.bar(EUR_USD, date(2026, 10, 2))
    assert bar is not None and bar.raw_key == "history/EURUSD-2026-10.zip#3"


def test_a_months_days_are_kept_beside_it_until_the_file_changes(tmp_path: Path) -> None:
    folder, cache = tmp_path / "history", tmp_path / "history-days"
    folder.mkdir()
    (folder / "EURUSD-2026-10.csv").write_text(OCTOBER, encoding="utf-8")
    History(folder, cache=cache).refresh()
    assert (cache / "EURUSD-2026-10.csv.json").is_file()
    again = History(folder, cache=cache)
    again.refresh()
    assert again.bar(EUR_USD, date(2026, 10, 2)) is not None
    (folder / "EURUSD-2026-10.csv").unlink()
    again.refresh()
    assert again.months == {}


def test_a_file_naming_no_pair_the_plugin_lists_is_not_read(tmp_path: Path) -> None:
    (tmp_path / "XAUUSD-2026-10.csv").write_text("XAU/USD,20261001 03:00:00.000,1,2\n")
    history = History(tmp_path)
    history.refresh()
    assert history.months == {}
