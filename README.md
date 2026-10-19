# plugin-truefx

TrueFX's FX rates in an Open Meridian deployment's lake: a data plugin. It
records TrueFX's top of book for each currency pair -- the bid and offer as a
quote, the mid as a price -- and each pair's day, built from TrueFX's ticks
on New York's day ending at 17:00: its close, its closing bid and offer, and
its bar. Every rate is recorded exactly as TrueFX quotes it, each pair named
as two cash instruments resolved through the master, nothing inverted or
crossed.

It is Open Meridian's first FX data plugin (approved 2026-10-13: "start with
Oanda and TrueFx"). TrueFX is a service of Integral; its rates are
indicative, not executable, from Integral's network.

**Status.** 0.2.0, built on open-meridian 0.31.0 (contract v26), holding the
role `data`. Not released, uploaded or launched anywhere. How to set it up
and use it is in [docs/](docs/README.md), which a deployment shows on its
Documentation tab (contract v25).

## What it does

Two datasets, declared from code in its catalogue (`declared.py`, part of
the version's whole declaration in `declaration.py`), their
names approved 2026-10-13:

| Dataset | Data | Modes | Day | Default terms |
|---|---|---|---|---|
| `<instance>:daily` | each pair's day: its close (the last mid), its closing bid and offer, as prices of kind `close`, `bid` and `ask`; and its bar of the mid | pull, push | `America/New_York`, ending at 17:00 | kept |
| `<instance>:live` | TrueFX's top of book: its bid and offer as a quote, its mid as a price of kind `mid` | pull, stream | `America/New_York`, ending at 17:00 | kept two days |

- **A pair is two cash instruments** (meridian-design `spec/the-lake.md`, Q3;
  ruled 2026-10-13, the spot-FX plugin's Q6: no pair record). Each currency
  TrueFX names is resolved through the master by its ISO 4217 code, and the
  plugin keeps its own pair map in its storage. A row's subject is the base
  currency's cash instrument and its price is in the quote currency, as
  TrueFX quotes it: EUR/USD is the euro's price in dollars, USD/JPY the
  dollar's in yen. A subject TrueFX quotes in no pair as the base -- the
  yen's own instrument -- is declined as not covered, never served by
  inverting USD/JPY. A subject another source resolved is named by reading
  its record for its ISO code.
- **What the lake wants, recorded.** A reader reads a price nothing has
  recorded; the lake asks this plugin (a want), which records it against
  the want or declines each subject with why: `not_covered` (no pair TrueFX
  serves has it as the base), `beyond_history` (before the first day the
  plugin holds), `source_silent` (TrueFX said nothing: a weekend, a day not
  reached). A standing want keeps its subjects current until the lake
  withdraws it: the live dataset from each poll, the daily dataset's forming
  day every five minutes.
- **The day** is the FX day: New York's, from 17:00 to 17:00 (the calendars
  spec's Q7; reference/fx-and-crypto-identifiers.md). A Sunday evening's
  tick is Monday's; a day is 23 or 25 hours across New York's clock change.
  The forming day is restated under the same row keys as it fills; a closed
  day carries its published time, the day's end, and is pushed once it
  closes, for every pair whose currencies resolved, wanted or not, and
  again if a late tick changes it.
- **A day's bar** is built from the ticks: the open, high, low and close of
  the mid. Its volume is 0, which the lake reads as "nothing traded": TrueFX's
  rates are indicative and nothing trades on it. A quote names no size,
  which TrueFX never states.
- **No venue.** TrueFX's rates are aggregated from Integral's network, no
  venue's, so neither dataset nor any row names one.

### TrueFX's sessions

From TrueFX's Market Data Web API Developer Guide (1.0v17), one address,
`https://webrates.truefx.com/rates/connect.html`, in two kinds of session:

- **Unauthenticated** (no username set): the address alone answers a
  snapshot of ten pairs -- EUR/USD, USD/JPY, GBP/USD, EUR/GBP, USD/CHF,
  EUR/JPY, EUR/CHF, USD/CAD, AUD/USD, GBP/JPY -- in TrueFX's default format,
  fixed-width columns. Nothing else can be asked of it.
- **Authenticated** (a TrueFX username set): a session is asked for once,
  with the username, a qualifier and the pairs, and TrueFX answers its ID;
  each poll then asks for that ID and gets, in CSV, only the pairs that moved
  since the last poll. It serves those ten and seventeen more, 27 in all.
  "not authorized" means TrueFX no longer knows the session; the plugin asks
  for a new one.

TrueFX's API asks for **no password and no token**: the guide calls the `p`
parameter "required for backwards compatibility" and lets it be any string,
so the plugin sends a fixed word. The free TrueFX account's username is the
only credential; its password is for TrueFX's website alone.

The plugin polls once a second, which TrueFX's guide does not limit; while
TrueFX does not answer it waits 2, 4, 8 ... seconds, at most a minute.

### History

TrueFX publishes its history as monthly tick files, one per pair, to
download from its website's Historical Downloads page with a free TrueFX
account ("Please log in or register for free access to the historical data
downloads"). There is no API for them. So the plugin never downloads them
and holds no website password: a person with a TrueFX account downloads the
months wanted and puts them, as TrueFX publishes them (`.csv`, or the `.zip`
holding one), in the plugin's storage under `history/`. The plugin reads
whatever is there each minute, every tick into its day, and serves a day from
the files where they hold every month the day touches -- the files' day, from
every tick TrueFX recorded, before the day it built from polling once a
second.

Each file is read as one tick a line: the pair, the time in GMT to the
millisecond, the bid and the offer (`EUR/USD,20261001 21:00:00.123,1.17012,
1.17015`). That is the layout public descriptions of TrueFX's files give; a
line that does not read is counted on the Datasets page, never guessed.

### What it cannot serve

The SDK's data suite names what a data plugin must do; a case about
something TrueFX never states is not presented, with why (`tests/test_suite.py`):

- a crypto asset's price, prices on a venue, a security's price: TrueFX's
  API quotes currency pairs, no venue's;
- trades, and every case about a trade's fields: nothing trades on TrueFX;
- a quote with its sizes, a one-sided quote: TrueFX states both sides, and
  no size;
- a settlement calendar and a settlement date: FX quotes need neither;
- an event contract's outcomes and its event group: TrueFX lists no event
  contract.

Contract v26's bounded query of the lake is mapped as the SDK's data
template maps it; the plugin itself asks the lake nothing. The cases every
suite holds are the SDK's.

## TrueFX's terms

TrueFX's terms for its data, and whether a deployment's use meets them, are
the deployment admin's to settle with TrueFX, never this plugin's: the
catalogue's default terms are a starting point the deployment's licence on
the Data sources page confirms or replaces. TrueFX describes its data as
indicative, not executable. Nothing here says that a deployment meets
TrueFX's terms.

**No real TrueFX response is committed** to this public repository: the
tests and sample data use a synthetic feed and history files
(`src/truefx/synthetic/`) in TrueFX's layouts, with invented values.

## Settings

| Setting | What it does |
|---|---|
| TrueFX username (`username`) | Secret, optional. A registered, confirmed TrueFX account's username, for an authenticated session's 27 pairs; empty, the plugin reads the 10 pairs TrueFX serves anyone. Entered by the person whose account it is; never logged, shown, or kept in a raw record. |
| Sample data (`sample_data`) | A developer's setting, shown only on a development deployment: answer from the synthetic feed and history files this plugin carries instead of calling TrueFX. |
| Raw responses' window (`responses_window_days`, `responses_past_window`) | The SDK's, for the plugin's one kind of raw record: how long TrueFX's answers stay in its storage (7 days by default), and whether a day past it is archived, kept or deleted. |

## Its pages, under Manage

The data role's two pages (meridian-design
`spec/plugin-pages-follow-their-role.md`), the same sections, rows, labels
and "not set up yet" states as every data plugin's, drawn from the SDK's
role templates (`meridian.roles.data`); TrueFX's nuance only at their
extension points. A data plugin shows no market data: viewing prices is for
the reading roles.

- **Connection**: "Key" -- the mode (Live, or Sample data), the TrueFX
  username set or not (never its value), what TrueFX serves the session (27
  pairs authenticated, 10 without), and the session; "Limits and use" --
  TrueFX states no limit, and the plugin polls once a second -- its calls,
  the last call and the last error; "Stream" -- "Does not stream": TrueFX's
  API is polled.
- **Datasets**: "Served" -- each dataset of its catalogue, its data, how its
  rows arrive, its day, its default terms and whether a deployment admin has
  licensed it, what it recorded and declined and when it last recorded;
  "Wants" -- the wants it heard and the standing wants it keeps current,
  searched and paged by the kit's `om-pager`; "Subjects"; then a section
  under TrueFX's name: the pairs with both currencies resolved, the
  currencies not resolved, the days built from its polls, and the history
  files held and the months they cover.

Its Summary carries the data role's figures, in the role's order:
Connection, Entitled at the vendor, Stream and Last recorded.

### Offered to agents

Each page is a read tool on the deployment's MCP surface, answering the record
the page shows: `read_connection` and `read_datasets`, at the plugin's admin
level. The plugin has no route that changes anything.

## Storage

- **Raw responses** (`responses/`): every answer TrueFX sends, "not
  authorized" and an error as much as a rate, kept before anything is read
  from it, with the request that asked for it (the session as `<session>`,
  never the username), its status and when it arrived (`raw.py`); a line of
  its hour's file, added only when the answer changed. Each row names its raw
  record and its line. Kept in units of a UTC day, moved past the window
  through the SDK.
- **The pair map** (`pairs.json`), **the days being built** (`days/`, a file
  per business date, so a restart carries on the day) and **the history
  files** a person put there (`history/`, with what was read of each under
  `history-days/`). Sample data's are apart, under `synthetic/`.

## Proven against a released runtime

    make e2e

runs the plugin on core's plugin harness, the runtime and harness of the
core it pins by digest (17a13a2, contract v26), the harness holding each
registration to the declaration printed from the image, beside the e2e's reader
(`e2e/reader.py`, a `reporting` plugin run from the plugin's image, holding
`custody` to resolve the currencies by their ISO codes and `signal` to read
quotes), its hosts file sending TrueFX's address nowhere: TrueFX unreachable
said on Connection and nothing recorded; the two datasets listed by the
deployment admin's tool on New York's day ending at 17:00; sample data's
polls building a day and pushing each of the ten pairs' rows, restated as
ticks came; the euro's close wanted from the history files (EUR/USD's, in
dollars) and the dollar's in yen, the yen's own instrument declined as not
covered; the euro's latest quotes recorded with no size; both read tools
answering what the pages show; `store lake` numbering each dataset's rows
with no holes; and, restarted, nothing recorded twice (`e2e/run.py` says each
step).

## Working on it

Plugins are CI-first (ruled 2026-10-13): a change goes on a branch and a pull
request, whose CI -- `ci`, `check` and `e2e` -- is the gate, and merges when
green.

    make ci-local        # every gate: lint, tests, plugin check, the image, e2e
    make test            # the tests, the SDK's data suite among them
    make preview         # preview/: each page on synthetic data, linking the kit
    make install-hooks   # a push to main runs ci-local first; a branch push nothing

`AGENTS.md` is for any coding agent working on it; `CLAUDE.md` leads Claude
Code there.

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`. TrueFX is a trademark of Integral
Development Corp.; this project is not affiliated with or endorsed by TrueFX
or Integral.
