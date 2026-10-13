"""What this version declares beside its role (W8.1, W4.1; contracts v18 to
v20): its catalogue, its storage and its settings.

**Its catalogue** (spec/the-lake, "The catalogue"; the names approved
2026-10-13), declared from code and read the same way at registration and by
`meridian plugin upload`:

- `daily`: each pair's day built from TrueFX's ticks -- its close (the last
  mid), its closing bid and offer as prices of kind bid and ask, and its bar
  of the mid -- on New York's day ending at 17:00 (`day_time_zone`
  America/New_York, `day_end_minute` 1020), the FX day. Pulled for what
  the lake wants, and pushed as each day closes; kept. Its history reaches
  as far back as the TrueFX history files a person puts in the plugin's
  storage (history.py), and otherwise to the first day it polled.
- `live`: TrueFX's top of book, its bid and offer as a quote and its mid as
  a price, polled once a second; pulled for the latest, or kept current for
  a standing want; kept two days.

TrueFX's rates are indicative, not executable, from Integral's network: no
venue's. So neither dataset names a venue, and no row does.

Each licence is the default a deployment's licence confirms or replaces on
the Data sources page, never a statement of what TrueFX's terms allow: they
are the deployment admin's to settle (README, "TrueFX's terms").

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
from meridian import DatasetDeclaration, DatasetLicence, Declaration, RecordKind, Storage

from .days import DAY_END_MINUTE, DAY_TIME_ZONE
from .raw import KIND, LABEL, WINDOW_DAYS

VENDOR = "TrueFX"
DAILY, LIVE = "daily", "live"
USERNAME, SAMPLE_DATA = "username", "sample_data"
#: Ten years, in days: as far back as TrueFX's files a person puts in
#: storage may reach (they start in 2009).
HISTORY_DAYS = 3650


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
        licence_default=DatasetLicence(kept=True, derived_use=True, display=True),
        day_time_zone=DAY_TIME_ZONE,
        day_end_minute=DAY_END_MINUTE,
    ),
    DatasetDeclaration(
        key=LIVE,
        vendor=VENDOR,
        data_types=["meridian.v1.Price", "meridian.v1.Quote"],
        modes=["pull", "stream"],
        cadence=1,
        history=0,
        licence_default=DatasetLicence(kept=True, retention_days=2, display=True),
        day_time_zone=DAY_TIME_ZONE,
        day_end_minute=DAY_END_MINUTE,
    ),
]

DECLARATION = Declaration(
    settings=Config,
    storage=Storage(kinds=[RecordKind(KIND, LABEL, window_days=WINDOW_DAYS)]),
    catalogue=CATALOGUE,
)
