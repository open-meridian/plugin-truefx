# Changelog

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
