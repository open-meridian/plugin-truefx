# Setup

## Before launching

Nothing is required: TrueFX serves ten pairs to anyone. For 27 pairs,
register a free account at [TrueFX](https://www.truefx.com) and confirm it;
the plugin needs only its username. TrueFX's API asks for no password and no
token, and the plugin never asks for the account's password.

## Launching it

Launch the plugin and approve its one role, `data` (a data plugin). It polls
TrueFX once its settings are delivered.

Its settings, in the dashboard's Settings form:

- **TrueFX username**: secret and optional. Entered by the person whose
  account it is; it is never shown, logged or kept in a raw record. Empty,
  the plugin reads the ten pairs TrueFX serves anyone.
- **Raw responses window** and **past the window** (the SDK's): how long
  TrueFX's answers stay in the plugin's storage, seven days by default, and
  whether a day past it is archived, kept or deleted.
- **Sample data**, on a deployment installed for development only: a
  made-up feed and history files carried in the plugin, in place of TrueFX.
  For trying it offline.

## Its datasets

On the deployment's **Data sources** page (deployment admins):

1. **License `<instance>:daily` and `<instance>:live`.** Each catalogue
   default is a starting point, not a statement of what TrueFX's terms
   allow: confirm it, or set your own, with a note saying why (see Terms).
2. **Entitle** each plugin that reads them, such as your reporting plugin
   or a signal plugin.
3. **Priority**, where another dataset also prices currencies: put the one
   your valuation should read first.

## Your currencies' instruments

Each pair is two currencies' cash instruments, found by their ISO 4217
codes. The Datasets page lists the currencies not resolved; a pair waits
until both its currencies resolve, and is recorded from the next poll.

## Adding history

To serve days before the plugin started polling:

1. Sign in at TrueFX and download the monthly files wanted from its
   Historical Downloads page.
2. Put each file as TrueFX publishes it, the `.csv` or the `.zip` holding
   one, in the plugin's storage under `history/`.
3. Within a minute the Datasets page lists the files held and the months
   they cover, and counts any line that did not read.

A day is served from the files only where they hold every month it touches.
