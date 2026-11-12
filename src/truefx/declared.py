"""The parts of this version's declaration beside its role (W8.1, W4.1;
contracts v18 to v20): its catalogue, its storage and its settings, which
the pages and the work import. declaration.py puts them together with the
interface and the documentation (contract v25), so it can import the pages.

**Its catalogue** (spec/the-lake, "The catalogue"; the names approved
2026-10-13), declared from code and read the same way at registration and by
`meridian plugin upload`:

- `daily`: each pair's day built from TrueFX's ticks -- its close (the last
  mid), its closing bid and offer as prices of kind bid and ask, and its bar
  of the mid -- on New York's day ending at 17:00 (`day_time_zone`
  America/New_York, `day_end_minute` 1020), the FX day. Pulled for what
  the lake wants, and pushed as each day closes. Its history reaches
  as far back as the TrueFX history files a person puts in the plugin's
  storage (history.py), and otherwise to the first day it polled.
- `live`: TrueFX's top of book, its bid and offer as a quote and its mid as
  a price, polled once a second; pulled for the latest, or kept current for
  a standing want.

TrueFX's rates are indicative, not executable, from Integral's network: no
venue's. So neither dataset names a venue, and no row does.

**Their declared delay** (contract v27, `declared_delay_ns`): none. TrueFX
describes its rates as "live, indicative prices" and states no delay, so
`live` is declared real time; `daily` is built by the plugin from those
same polls, each day recorded as it closes, so it is real time too. A
reader judges their staleness and feed delay against the ceilings alone.

**Their terms and pricing** (contract 30, ruling 1032): TrueFX's terms in
plain words (`terms_and_pricing`), shown on Data sources and in the plugin's
docs, never a licence: the licence a deployment admin sets is the one
enforced, and TrueFX's terms are the deployment admin's to settle (README,
"TrueFX's terms").

**How a gap is recovered** (contract 30, `gap_recovery`): `daily` by
`backfill` -- the lake asks again for the days, which the plugin builds
again from its polls and the history files it holds -- and `live` is
`stream_only`: a tick missed is never served again.

**Its storage**: one kind of raw record, TrueFX's responses as received,
kept a week by default (raw.py); the SDK declares the kind's two window
settings. The pair map, the days being built and the history files a person
puts there live in the same storage (README, "Storage").

**Its settings**, in the data role's order: no environment (TrueFX has one
service), the credential -- the TrueFX username, for an authenticated
session's twenty-seven pairs, secret, optional (without it the plugin reads
the ten pairs TrueFX serves anyone) -- and sample data, a developer's.
TrueFX's API asks for no password and no token (client.py).
"""

from __future__ import annotations

import meridian
from meridian import DatasetDeclaration, RecordKind

from .days import DAY_END_MINUTE, DAY_TIME_ZONE
from .raw import KIND, LABEL, WINDOW_DAYS

VENDOR = "TrueFX"
DAILY, LIVE = "daily", "live"
USERNAME, SAMPLE_DATA = "username", "sample_data"
#: Ten years, in days: as far back as TrueFX's files a person puts in
#: storage may reach (they start in 2009).
HISTORY_DAYS = 3650
#: TrueFX's terms and pricing in plain words (contract 30, ruling 1032), as
#: truefx.com describes its service: what it serves, who, and at what cost.
TERMS = (
    "TrueFX is a service of Integral Development Corp.: indicative, not executable, "
    "foreign-exchange rates from Integral's network, named for no venue. Free of charge: "
    "without an account its API serves 10 pairs, and a registered, confirmed account's "
    "username opens an authenticated session of 27 pairs; its monthly history files are "
    "for account holders to download from its website. TrueFX's own terms on "
    "truefx.com govern the use of its data; check them there, as they can change."
)
#: How far behind real time TrueFX serves its rates: not at all, as it
#: describes them ("live, indicative prices"; truefx.com, read 2026-10-24).
DECLARED_DELAY_NS = 0


@meridian.settings
class Config:
    """The settings, in the data role's order: the credential, then sample
    data."""

    username: str = meridian.setting(
        "TrueFX username",
        secret=True,
        description=(
            "The username of a registered, confirmed TrueFX account, for an authenticated "
            "session: 27 pairs rather than 10. TrueFX's API asks for no password. Leave it "
            "empty to read the 10 pairs TrueFX serves without an account."
        ),
    )
    sample_data: bool = meridian.sample_data(
        description=(
            "Answer from the plugin's built-in made-up TrueFX feed and history files instead "
            "of calling TrueFX. Development deployments only."
        )
    )


CATALOGUE = [
    DatasetDeclaration(
        key=DAILY,
        vendor=VENDOR,
        data_types=["meridian.v1.Price", "meridian.v1.Bar"],
        modes=["pull", "push"],
        cadence=86_400,
        history=HISTORY_DAYS,
        terms_and_pricing=TERMS,
        gap_recovery="backfill",
        day_time_zone=DAY_TIME_ZONE,
        day_end_minute=DAY_END_MINUTE,
        declared_delay_ns=DECLARED_DELAY_NS,
    ),
    DatasetDeclaration(
        key=LIVE,
        vendor=VENDOR,
        data_types=["meridian.v1.Price", "meridian.v1.Quote"],
        modes=["pull", "stream"],
        cadence=1,
        history=0,
        terms_and_pricing=TERMS,
        gap_recovery="stream_only",
        day_time_zone=DAY_TIME_ZONE,
        day_end_minute=DAY_END_MINUTE,
        declared_delay_ns=DECLARED_DELAY_NS,
    ),
]

#: Its one kind of raw record, TrueFX's responses (raw.py).
RESPONSES_KIND = RecordKind(KIND, LABEL, window_days=WINDOW_DAYS)
