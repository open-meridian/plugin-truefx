"""TrueFX's Market Data Web API, as this plugin calls it.

From TrueFX's Market Data Web API Developer Guide (1.0v17): one address,
`https://webrates.truefx.com/rates/connect.html`, asked over HTTPS, in one of
two kinds of session.

- **Unauthenticated**: the address with no query answers a snapshot of ten
  pairs in the default format (rates.py). Nothing else is asked of it.
- **Authenticated**, with a registered, confirmed TrueFX username: a session
  is asked for with `u` (the username), `p`, `q` (a qualifier), `c` (the
  pairs), `f=csv` and `s=n`, and TrueFX answers its ID,
  `username:password:qualifier:digits`. Each poll then asks `id=<that ID>`
  and is answered in CSV with only the pairs that moved since the last
  poll. The guide says `p` is "required for backwards compatibility" and
  may be "any string of one or more alphanumeric characters": TrueFX asks
  for no password and no token, so the plugin sends a fixed word and holds
  no password. "not authorized" means TrueFX no longer knows the session (it
  expired, or a server failed over): the next poll asks for a new one.

Each response is kept as a raw record before it is read (raw.py), and every
call is counted for the Connection page: calls, failures, the last error,
when the session was opened. The username is never logged, kept or shown.

The transport is the standard library's HTTP client, or with sample data the
synthetic feed (synthetic.py), which answers the same requests.
"""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from .pairs import Pair, served
from .rates import NOT_AUTHORIZED, Rate, Read, is_session_id, read_csv, read_default
from .raw import RawStore

log = logging.getLogger(__name__)

ADDRESS = "https://webrates.truefx.com/rates/connect.html"
#: The qualifier naming this plugin's session, and the word sent as `p`,
#: which TrueFX does not check (the guide: "Any string").
QUALIFIER = "meridian"
PASSWORD_WORD = "meridian"
TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Response:
    status: int
    body: str


#: A transport: an address to its response; raises on a network failure.
Transport = Callable[[str], Response]


def https(url: str) -> Response:
    """TrueFX over HTTPS, with the standard library's client."""
    request = urllib.request.Request(url, headers={"User-Agent": "open-meridian-truefx"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as answered:  # noqa: S310
            return Response(answered.status, answered.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as refused:
        return Response(refused.code, refused.read().decode("utf-8", "replace"))


@dataclass
class Health:
    """What the plugin asked of TrueFX since it started, for Connection."""

    calls: int = 0
    failures: int = 0
    last_ok_ns: int = 0
    last_failed_ns: int = 0
    last_error: str = ""
    sessions_opened: int = 0
    session_opened_ns: int = 0
    unread: int = 0


@dataclass
class TrueFX:
    """TrueFX's API: a session, kept and asked again when lost, and each
    poll's rates."""

    store: RawStore
    transport: Transport = https
    #: "live", "synthetic" (the package's synthetic feed) or "recorded".
    mode: str = "live"
    username: str = field(default="", repr=False)
    address: str = ADDRESS
    clock_ns: Callable[[], int] = time.time_ns
    session_id: str = field(default="", repr=False)
    health: Health = field(default_factory=Health)

    @property
    def authenticated(self) -> bool:
        return bool(self.username)

    @property
    def pairs(self) -> tuple[Pair, ...]:
        return served(self.authenticated)

    def use_username(self, username: str) -> None:
        """A username set, changed or cleared: the session asked for again."""
        if username != self.username:
            self.username = username
            self.session_id = ""

    def _ask(self, url: str, request: str) -> tuple[Response | None, int]:
        self.health.calls += 1
        try:
            answered = self.transport(url)
        except (OSError, ValueError) as failed:
            # Said by its type and reason, never its text, which may hold
            # the address asked, and so the username.
            reason = getattr(failed, "reason", None) or getattr(failed, "strerror", None)
            self._failed(type(failed).__name__ + (f": {reason}" if isinstance(reason, str) else ""))
            return None, self.clock_ns()
        received = self.clock_ns()
        if answered.status != 200:
            self._failed(f"TrueFX answered {answered.status} to {request}")
            return None, received
        return answered, received

    def _failed(self, why: str) -> None:
        self.health.failures += 1
        self.health.last_failed_ns = self.clock_ns()
        self.health.last_error = why
        log.warning("TrueFX: %s", why)

    def _ok(self) -> None:
        self.health.last_ok_ns = self.clock_ns()

    def _keep(self, request: str, received_ns: int, response: Response) -> str:
        return self.store.keep(
            "rates",
            {
                "request": request,
                "received_at_ns": received_ns,
                "status": response.status,
                "body": response.body,
                "mode": self.mode,
            },
        )

    def _open(self) -> bool:
        """Ask for an authenticated session; whether one was opened."""
        query = urllib.parse.urlencode(
            {
                "u": self.username,
                "p": PASSWORD_WORD,
                "q": QUALIFIER,
                "c": ",".join(pair.symbol for pair in self.pairs),
                "f": "csv",
                "s": "n",
            },
            safe="/,",
        )
        answered, received = self._ask(f"{self.address}?{query}", "a session request")
        if answered is None:
            return False
        said = answered.body.strip()
        if not is_session_id(said, self.username, QUALIFIER):
            # TrueFX's refusal kept as said; any other answer, which may echo
            # the username, kept as what it was.
            kept = said if said.lower() == NOT_AUTHORIZED else "<not a session ID>"
            self._keep("connect.html?u=<username>&q=meridian&f=csv&s=n", received,
                       Response(answered.status, kept))  # fmt: skip
            self._failed(
                "TrueFX did not open a session for this username"
                + (": not authorized" if NOT_AUTHORIZED in said.lower() else "")
            )
            return False
        self._keep("connect.html?u=<username>&q=meridian&f=csv&s=n", received,
                   Response(answered.status, "<session id>"))  # fmt: skip
        self.session_id = said
        self.health.sessions_opened += 1
        self.health.session_opened_ns = received
        self._ok()
        return True

    def poll(self) -> Read:
        """One poll: every pair an unauthenticated session serves, or what
        moved since the last poll of an authenticated one."""
        if not self.authenticated:
            answered, received = self._ask(self.address, "a snapshot")
            if answered is None:
                return Read(())
            key = self._keep("connect.html", received, answered)
            read = read_default(answered.body, key)
            return self._read(read, answered.body)
        if not self.session_id and not self._open():
            return Read(())
        query = urllib.parse.urlencode({"id": self.session_id}, safe=":")
        answered, received = self._ask(f"{self.address}?{query}", "a poll")
        if answered is None:
            return Read(())
        key = self._keep("connect.html?id=<session>", received, answered)
        if NOT_AUTHORIZED in answered.body.lower():
            self.session_id = ""
            self._failed("TrueFX no longer knows the session: not authorized; asked again")
            return Read(())
        return self._read(read_csv(answered.body, key), answered.body)

    def _read(self, read: Read, body: str) -> Read:
        if read.unread:
            self.health.unread += len(read.unread)
            log.warning("TrueFX: %d groups did not read", len(read.unread))
        if body.strip() and not read.rates and read.unread:
            self._failed("TrueFX's answer did not read: " + read.unread[0][:120])
        else:
            self._ok()
        return read


def latest(rates: tuple[Rate, ...]) -> dict[Pair, Rate]:
    """Each pair's latest rate among `rates`."""
    found: dict[Pair, Rate] = {}
    for rate in rates:
        held = found.get(rate.pair)
        if held is None or rate.at_ms >= held.at_ms:
            found[rate.pair] = rate
    return found
