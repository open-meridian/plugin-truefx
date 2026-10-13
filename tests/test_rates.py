"""TrueFX's two rate formats, read exactly, as its developer guide lays them
out; and what does not read, never guessed."""

from __future__ import annotations

from decimal import Decimal

from truefx.rates import GROUP, is_session_id, read_csv, read_default
from truefx.synthetic import default_body, steps


def test_a_csv_rate_is_its_big_figure_and_points_written_together() -> None:
    body = (
        "EUR/USD,1791547200003,1.16,431,1.16,434,1.16495,1.16359,1.16440\n"
        "USD/JPY,1791547200020,149.,512,149.,515,149.576,149.440,149.521\n"
    )
    read = read_csv(body, "responses/2026-10-09/rates-12.jsonl#0")
    eur, jpy = read.rates
    assert (eur.pair.symbol, eur.at_ms, eur.bid, eur.ask) == (
        "EUR/USD", 1791547200003, Decimal("1.16431"), Decimal("1.16434"))  # fmt: skip
    assert (eur.high, eur.low, eur.open) == (
        Decimal("1.16495"), Decimal("1.16359"), Decimal("1.16440"))  # fmt: skip
    assert (str(jpy.bid), str(jpy.ask)) == ("149.512", "149.515")
    assert str(eur.mid) == "1.164325" and str(jpy.mid) == "149.5135"
    assert eur.raw_key == "responses/2026-10-09/rates-12.jsonl#0"
    assert read.unread == ()


def test_groups_separated_by_spaces_as_the_guide_writes_them_read_too() -> None:
    body = (
        "AUD/USD,1791547200139,0.65,012,0.65,015,0.65076,0.64940,0.65021 "
        "GBP/JPY,1791547200156,201.,250,201.,258,201.319,201.178,201.259"
    )
    assert [str(r.bid) for r in read_csv(body).rates] == ["0.65012", "201.250"]


def test_a_group_that_does_not_read_is_kept_as_not_read() -> None:
    body = (
        "EUR/USD,1791547200003,1.16,431,1.16,434,1.16495,1.16359,1.16440 "
        "XAU/USD,1791547200003,2650.,10,2650.,50,1,1,1 "
        "EUR/GBP,notatime,0.86,490,0.86,494,0.8,0.8,0.8 "
        "EUR/CHF,1791547200003,0.92,9x5,0.92,980,0.9,0.9,0.9"
    )
    read = read_csv(body)
    assert [r.pair.symbol for r in read.rates] == ["EUR/USD"]
    assert len(read.unread) == 3


def test_the_default_format_reads_its_fixed_width_columns() -> None:
    # Two pairs, as the guide lays the default format out: the symbols, then
    # each column of each pair in turn, big figures padded in front with #.
    body = (
        "EUR/USDUSD/JPY"
        "1.16#89."
        "431512"
        "1.16#89."
        "434515"
        "1.16495#89.576"
        "1.16359#89.440"
        "17915472000031791547200020"
    )
    assert len(body) == 2 * GROUP
    eur, jpy = read_default(body, "responses/x.jsonl#3").rates
    assert (str(eur.bid), str(eur.ask), str(eur.high), str(eur.low)) == (
        "1.16431", "1.16434", "1.16495", "1.16359")  # fmt: skip
    assert (str(jpy.bid), str(jpy.ask), str(jpy.high)) == ("89.512", "89.515", "89.576")
    assert jpy.at_ms == 1791547200020 and eur.open is None


def test_the_synthetic_snapshot_is_the_default_format_of_its_ten_pairs() -> None:
    read = read_default(default_body(steps()[0]))
    assert len(read.rates) == 10 and read.unread == ()
    assert str(read.rates[9].bid) == "201.250"


def test_a_default_body_of_no_whole_number_of_pairs_is_not_read() -> None:
    read = read_default("EUR/USD1.16")
    assert read.rates == () and len(read.unread) == 1
    assert read_default("").rates == ()


def test_a_session_id_is_the_username_the_word_the_qualifier_and_digits() -> None:
    assert is_session_id("jsTrader:string:meridian:1253889202204", "jsTrader", "meridian")
    assert not is_session_id("not authorized", "jsTrader", "meridian")
    assert not is_session_id("other:string:meridian:12", "jsTrader", "meridian")
    assert not is_session_id("jsTrader:string:meridian:", "jsTrader", "meridian")
