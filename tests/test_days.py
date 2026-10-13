"""The FX day, New York's ending at 17:00, and the bars built in it."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from truefx.days import DayBook, business_date, day_bounds
from truefx.pairs import BY_SYMBOL
from truefx.rates import Rate

from conftest import ns

EUR_USD = BY_SYMBOL["EUR/USD"]


def rate(at: str, bid: str, ask: str, raw: str = "") -> Rate:
    return Rate(EUR_USD, ns(at) // 1_000_000, Decimal(bid), Decimal(ask), raw_key=raw)


def test_a_business_date_turns_at_17_00_new_york() -> None:
    # 16:59:59 and 17:00 New York (EDT, UTC-4) on Thursday 8 October 2026.
    assert business_date(ns("2026-10-08T20:59:59")) == date(2026, 10, 8)
    assert business_date(ns("2026-10-08T21:00:00")) == date(2026, 10, 9)
    # A Sunday evening's tick is Monday's.
    assert business_date(ns("2026-10-11T21:05:00")) == date(2026, 10, 12)
    # EST (UTC-5) from 1 November 2026.
    assert business_date(ns("2026-11-10T21:30:00")) == date(2026, 11, 10)
    assert business_date(ns("2026-11-10T22:00:00")) == date(2026, 11, 11)


def test_a_day_is_23_or_25_hours_across_new_yorks_clock_change() -> None:
    start, end = day_bounds(date(2026, 10, 9))
    assert (start, end) == (ns("2026-10-08T21:00:00"), ns("2026-10-09T21:00:00"))
    start, end = day_bounds(date(2026, 11, 1))  # clocks back at 02:00 on Sunday 1 November
    assert (end - start) // 3_600_000_000_000 == 25
    start, end = day_bounds(date(2027, 3, 14))  # forward at 02:00 on Sunday 14 March 2027
    assert (end - start) // 3_600_000_000_000 == 23


def test_a_bar_is_the_mids_open_high_low_close_and_the_closing_bid_and_offer() -> None:
    book = DayBook()
    for at, bid, ask in (("2026-10-08T21:05:00", "1.16380", "1.16384"),
                         ("2026-10-09T03:00:00", "1.16410", "1.16420"),
                         ("2026-10-09T09:00:00", "1.16300", "1.16304"),
                         ("2026-10-09T20:59:00", "1.16350", "1.16353")):  # fmt: skip
        assert book.add(rate(at, bid, ask, raw=f"r#{at}"))
    bar = book.get(EUR_USD, date(2026, 10, 9))
    assert bar is not None
    assert [str(v) for v in (bar.open, bar.high, bar.low, bar.close)] == [
        "1.16382", "1.16415", "1.16302", "1.163515"]  # fmt: skip
    assert (str(bar.bid), str(bar.ask), bar.ticks) == ("1.16350", "1.16353", 4)
    assert bar.raw_key == "r#2026-10-09T20:59:00"


def test_a_tick_heard_again_or_out_of_order_changes_nothing() -> None:
    book = DayBook()
    assert book.add(rate("2026-10-09T03:00:00", "1.1", "1.2"))
    assert not book.add(rate("2026-10-09T03:00:00", "1.1", "1.2"))
    assert not book.add(rate("2026-10-09T02:00:00", "1.3", "1.4"))
    bar = book.get(EUR_USD, date(2026, 10, 9))
    assert bar is not None and bar.ticks == 1


def test_the_book_is_kept_in_storage_and_read_back(tmp_path: Path) -> None:
    book = DayBook(tmp_path)
    book.add(rate("2026-10-09T03:00:00", "1.16410", "1.16420"))
    book.save()
    assert (tmp_path / "days" / "2026-10-09.json").is_file()
    again = DayBook(tmp_path)
    assert again.held_days() == [date(2026, 10, 9)]
    bar = again.get(EUR_USD, date(2026, 10, 9))
    assert bar is not None and bar.close == Decimal("1.16415")
    assert again.add(rate("2026-10-09T04:00:00", "1.16510", "1.16520"))
    later = again.get(EUR_USD, date(2026, 10, 9))
    assert later is not None and later.open == Decimal("1.16415") and later.ticks == 2


def test_two_halves_of_a_day_merge_into_one_bar() -> None:
    early, late = DayBook(), DayBook()
    early.add(rate("2026-09-30T21:05:00", "1.10000", "1.10002"))
    early.add(rate("2026-09-30T23:00:00", "1.10100", "1.10102"))
    late.add(rate("2026-10-01T03:00:00", "1.09900", "1.09902"))
    first = early.get(EUR_USD, date(2026, 10, 1))
    second = late.get(EUR_USD, date(2026, 10, 1))
    assert first is not None and second is not None
    merged = second.merged(first)
    assert [str(v) for v in (merged.open, merged.high, merged.low, merged.close)] == [
        "1.10001", "1.10101", "1.09901", "1.09901"]  # fmt: skip
    assert merged.ticks == 3
