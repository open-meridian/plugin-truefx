# Changelog

## 0.4.1

SDK 0.33.4: raw-record writes and enum conversion fixes (ruling 937).

- **The pins:** open-meridian 0.33.1 to 0.33.4, and plugin-python:0.33.4 by tag
  and digest (`meridian plugin migrate --to 0.33.4`: only the pins move).

## 0.4.0

On open-meridian 0.33.1, contract v28 (plugin-common-v28), on core v28's
harness.

- **The feed delay, reported** (ruling 518, required again from contract
  v28): each row recorded unasked or for a standing want has its age at
  the edge recorded (`Work.latency`, a `roles.Latency` `__main__` gives it),
  reported every 10 seconds (`ReportLatency`).
- **The edge's checks** (ruling 424): the same rows judged by the SDK's
  `quality.EdgeChecks` on the plugin's clock, as the SDK's `Wants.record`
  does for the plugins on it; `a-crossed-quote-is-recorded-invalid` is
  presented on a euro quote whose bid is above its offer.
- **Not presented** (ruling 602): option chains, filings, holdings,
  dividends and ratings, which TrueFX never states; the duplicate and gap
  cases, since its rates are polled and number no message.
- **`meridian plugin migrate`** (to_0_33_0, to_0_33_1): e2e/reader.py's and
  work.py's SubjectRefs are `meridian.SubjectRef` (ruling 599).
- **The pins:** open-meridian 0.33.1 and plugin-python:0.33.1 by tag and
  digest; core v28's runtime and harness at `8def82a` (chart 0.1.313) by
  digest; `meridian` stays 0.1.52 in check.yaml.
- The README's "Not released" line is gone.

## 0.3.0

On open-meridian 0.32.2, contract v27: the live dataset's liveness recorded,
the datasets' delay declared, and the suite's v27 cases mapped or not
presented honestly. The rows it records are unchanged.

- **Liveness** (contract v27, W10.4; ruling 418). While a standing want
  keeps `live` current, each poll TrueFX answers is recorded as the
  dataset's sign of life (`RecordLiveness`, `Work.alive`), once a poll, at
  the poll's time. An authenticated session answers only the pairs that
  moved, so an empty answer is TrueFX's heartbeat and confirms the quotes in
  force. A failed poll records nothing, nor does a poll with no standing want
  on `live`. `records-a-datasets-liveness` is presented.
- **The declared delay** (contract v27, `declared_delay_ns`): 0 on both
  datasets, declared explicitly. TrueFX describes its rates as "live,
  indicative prices" and states no delay; `daily` is built from the same
  polls.
- **The bounded lake query is no longer faked.**
  `queries-the-lake-within-bounds` is about trades from contract v27, and
  the plugin records none, so it is not presented ("it records no trades")
  rather than mapped to the SDK's `lake_query`.
- **The suite's other v27 cases**: the rates cases not presented (no
  reference rate, curve or index level), and `reports-its-feed-delay` not
  presented, as ruling 518 says: core receives ReportLatency from contract
  v28.
- **The Datasets page fits one screen** at 375, 582 and 1280 px, checked
  in a browser, before the lake has asked anything too: TrueFX's line gives
  the history files' months as one span, first to last, however many files
  a person adds (`read_datasets` answers it as `history_span`, beside the
  full `history_months`), says "pairs resolved", and leaves out a count with
  nothing to say (no days built yet, nothing restated or unchanged).
- **e2e**: step 6 lists the datasets as the reader sees them: the live
  dataset's liveness recorded, and no delay declared on either; step 7 reads
  the new history line. The failure's logs under `.e2e/` are uploaded
  (`include-hidden-files`).
- **The pins**: open-meridian 0.32.2 and plugin-python:0.32.2 by tag; core
  v27's runtime and harness (a5da59a, merged as 6d346b3, chart 0.1.310) by
  tag and digest; `meridian` 0.1.52 in check.yaml.
- The README, docs/overview.md and the workflows' words about the pins,
  the liveness and the delay brought up to date.

## 0.2.0

On open-meridian 0.31.0, contract v26: the plugin moves from contract v22,
as ruled (174: TrueFX moves to v25 as a follow-up, and is re-pinned with
v26). What it records and shows is unchanged.

- **The whole declaration (contract v25).** `declaration.py` is all the
  version says about itself: its settings, catalogue and storage (moved to
  `declared.py`, which the pages and work import), its interface (its two
  pages and the tools their routes make) on a port fixed at 8000, no longer
  read from `TRUEFX_PAGE_PORT`, and `documentation="docs"`. `__main__`
  connects with it alone.
- **docs/**: overview, setup, pages, troubleshooting and terms, which a
  deployment shows on the plugin's Documentation tab, with the repository's
  own index; the Dockerfile copies them to `/plugin/docs`.
- **Suites.** Contract v23's outcome cases (and v26's event-group and flag
  cases, about outcomes) not presented: TrueFX lists no event contract.
  v26's `queries-the-lake-within-bounds` mapped as the SDK's data template
  maps it; the plugin itself asks the lake nothing. The every-role cases are
  the SDK's. `tests/test_version_declaration.py`: the declaration as the
  upload reads it.
- **e2e:** the harness holds each registration to the declaration printed
  from the image (the reader's too), and takes the harness down with
  `--profile runner`.
- **The pins**: open-meridian 0.31.0 and plugin-python:0.31.0 by tag; core
  v26's runtime and harness (17a13a2, merged as 648e25f, chart 0.1.308) by
  tag and digest; `meridian` 0.1.48 in check.yaml.

Earlier versions are described in the git history.
