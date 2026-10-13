"""TrueFX's API as the plugin calls it: the two kinds of session, a lost
session asked again, failures counted, and the username never kept."""

from __future__ import annotations

from pathlib import Path

from truefx.client import Response, TrueFX
from truefx.raw import RawStore
from truefx.synthetic import Synthetic

NOW = 1_791_547_200 * 1_000_000_000


def client(tmp_path: Path, transport: object, username: str = "") -> TrueFX:
    return TrueFX(RawStore(tmp_path), transport, "synthetic", username,  # type: ignore[arg-type]
                  clock_ns=lambda: NOW)  # fmt: skip


def kept(tmp_path: Path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in sorted(tmp_path.rglob("*.jsonl")))


def test_an_unauthenticated_poll_asks_the_address_alone_for_ten_pairs(tmp_path: Path) -> None:
    asked: list[str] = []
    synthetic = Synthetic()

    def transport(url: str) -> Response:
        asked.append(url)
        return synthetic(url)

    truefx = client(tmp_path, transport)
    read = truefx.poll()
    assert asked == ["https://webrates.truefx.com/rates/connect.html"]
    assert len(read.rates) == 10 and len(truefx.pairs) == 10
    assert read.rates[0].raw_key == "responses/2026-10-09/rates-12.jsonl#0"
    assert truefx.health.calls == 1 and truefx.health.failures == 0


def test_an_authenticated_session_is_asked_for_once_then_polled(tmp_path: Path) -> None:
    asked: list[str] = []
    synthetic = Synthetic()

    def transport(url: str) -> Response:
        asked.append(url)
        return synthetic(url)

    truefx = client(tmp_path, transport, username="jsTrader")
    first = truefx.poll()
    second = truefx.poll()
    assert asked[0].startswith("https://webrates.truefx.com/rates/connect.html?u=jsTrader&p=")
    assert "&q=meridian&c=EUR/USD,USD/JPY," in asked[0] and asked[0].endswith("&f=csv&s=n")
    assert asked[1:] == ["https://webrates.truefx.com/rates/connect.html?id="
                         "jsTrader:string:meridian:1791547200000"] * 2  # fmt: skip
    assert len(first.rates) == 10 and [r.pair.symbol for r in second.rates] == [
        "EUR/USD", "USD/JPY"]  # fmt: skip
    assert truefx.health.sessions_opened == 1 and len(truefx.pairs) == 27
    # The username is in no raw record: the session's answer is kept redacted.
    assert "jsTrader" not in kept(tmp_path) and "<session id>" in kept(tmp_path)


def test_not_authorized_drops_the_session_and_the_next_poll_asks_again(tmp_path: Path) -> None:
    answers = iter(["jsTrader:string:meridian:1", "not authorized",
                    "jsTrader:string:meridian:2", ""])  # fmt: skip
    asked: list[str] = []

    def transport(url: str) -> Response:
        asked.append(url)
        return Response(200, next(answers))

    truefx = client(tmp_path, transport, username="jsTrader")
    assert truefx.poll().rates == ()
    assert truefx.session_id == "" and "not authorized" in truefx.health.last_error
    truefx.poll()
    assert truefx.health.sessions_opened == 2 and truefx.session_id.endswith(":2")
    assert "?u=" in asked[2]


def test_a_username_trueFX_does_not_know_is_said_without_the_username(tmp_path: Path) -> None:
    truefx = client(tmp_path, lambda url: Response(200, "not authorized"), username="secretname")
    assert truefx.poll().rates == ()
    assert "did not open a session" in truefx.health.last_error
    assert "secretname" not in truefx.health.last_error and "secretname" not in kept(tmp_path)


def test_a_failure_is_counted_and_said(tmp_path: Path) -> None:
    def refused(url: str) -> Response:
        raise ConnectionRefusedError(61, "Connection refused")

    truefx = client(tmp_path, refused)
    assert truefx.poll().rates == ()
    assert truefx.health.failures == 1
    assert truefx.health.last_error == "ConnectionRefusedError: Connection refused"
    truefx.transport = lambda url: Response(503, "busy")
    truefx.poll()
    assert truefx.health.last_error == "TrueFX answered 503 to a snapshot"


def test_a_username_changed_asks_for_a_new_session(tmp_path: Path) -> None:
    truefx = client(tmp_path, Synthetic(), username="jsTrader")
    truefx.poll()
    truefx.use_username("other")
    assert truefx.session_id == ""
    truefx.use_username("")
    assert not truefx.authenticated and len(truefx.pairs) == 10


def test_an_unchanged_answer_is_kept_once(tmp_path: Path) -> None:
    truefx = client(tmp_path, lambda url: Response(200, ""), username="")
    truefx.poll()
    truefx.poll()
    assert kept(tmp_path).count("\n") == 1
