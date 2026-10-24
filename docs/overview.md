# Overview

TrueFX, a service of Integral, publishes indicative FX rates: a bid and an
offer for each currency pair, from Integral's network. This plugin polls
TrueFX once a second and puts its rates into your deployment's lake, where a
reporting plugin values your positions in another currency and a signal
plugin reads the latest quotes.

It is a data plugin: its first-use path, its two pages and its Summary figures are every data plugin's, described once on [Using a data plugin](https://open-meridian.dev/how-to/using-a-data-plugin/). These sections cover what is TrueFX's own.

## What it records

Two datasets:

- **`<instance>:daily`**, each pair's day, built from TrueFX's ticks: its
  close (the last mid), its closing bid and offer, and its bar of the mid.
  Pushed as each day closes, and pulled for a past day the lake wants.
- **`<instance>:live`**, TrueFX's top of book: its bid and offer as a quote,
  its mid as a price. Pulled for the latest, or kept current while a reader
  wants it. Kept two days by default.

Neither dataset declares a delay: TrueFX describes its rates as live.

## Liveness

While a reader keeps the live dataset current, each poll TrueFX answers is
recorded as the dataset's sign of life, once a poll. With a TrueFX username
the session answers only the pairs that moved, so a quiet second still
confirms the quotes in force, and a quote unchanged for a while is not taken
as stale while TrueFX keeps answering. When TrueFX stops answering, nothing
is recorded, and the quotes age.

## What a rate means here

A pair is two currencies' cash instruments, each found by its ISO 4217 code.
A row's subject is the base currency and its price is in the quote currency,
exactly as TrueFX quotes it: **EUR/USD 1.17012** is the euro's price in
dollars, **USD/JPY** the dollar's price in yen. Nothing is inverted or
crossed: the yen's own price is not covered, since TrueFX quotes no pair with
the yen as its base.

## The day

The FX day: New York's, from 17:00 to 17:00. A Sunday evening's tick belongs
to Monday. The forming day is restated as ticks arrive; a closed day is
pushed once, and again if a late tick changes it.

## Which pairs

- **Without a TrueFX username**, TrueFX serves anyone ten pairs: EUR/USD,
  USD/JPY, GBP/USD, EUR/GBP, USD/CHF, EUR/JPY, EUR/CHF, USD/CAD, AUD/USD and
  GBP/JPY.
- **With the username of a free TrueFX account**, an authenticated session
  serves those ten and seventeen more, 27 in all.

## History

TrueFX publishes its history as monthly tick files on its website, for
account holders to download; it offers no API for them. The plugin never
downloads them. A person with a TrueFX account downloads the months wanted
and puts them in the plugin's storage under `history/` (Setup says how); the
plugin reads them each minute and serves a day from them where they cover it.

## What it does not do

- It shows no rate on its own pages: rates are read by the plugins that use
  them.
- It records no trade and no size: TrueFX's rates are indicative, nothing
  trades on it, and a quote states no size. A day's bar carries volume 0.
- It names no venue: the rates are aggregated from Integral's network.
- It never inverts or crosses a rate, and never fills a missing day.
