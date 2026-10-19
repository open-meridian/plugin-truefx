# Troubleshooting

## Reaching TrueFX

| What you see | What it means | What to do |
|---|---|---|
| **Not answering** | No poll has reached TrueFX: no network, a proxy, or TrueFX down | Check the deployment's outbound access to webrates.truefx.com; the plugin tries again after 2, 4, 8 ... seconds, at most a minute apart |
| **10 pairs, unauthenticated** with a username set | TrueFX did not open an authenticated session for the username | Check the username is a registered, confirmed TrueFX account's; the last error says what TrueFX answered |

## Currencies and subjects

| What you see | What it means | What to do |
|---|---|---|
| Datasets: **not resolved:** and a currency's code | Its ISO 4217 code found no cash instrument, or two | Complete or merge the instrument at the Instruments page; its pairs are recorded from the next poll |
| A subject declined, *not covered* | No pair TrueFX serves has it as the base: the yen's own price, for one | Read the other currency's price in it, and invert it in the reader |

## Days and history

| What you see | What it means | What to do |
|---|---|---|
| A day declined, *beyond history* | The day is before the first day the plugin holds | Add TrueFX's history files for that month (Setup, "Adding history") |
| A day declined, *source silent* | TrueFX said nothing for it: a weekend, or a day the plugin did not reach | Nothing to do for a weekend; otherwise add the month's history files |
| Datasets: **lines did not read** | A line of a history file is not in TrueFX's layout | Download the month again from TrueFX; a line that does not read is counted, never guessed |

## Licensing

| What you see | What it means | What to do |
|---|---|---|
| Datasets: **Not licensed yet** | No deployment admin has licensed the dataset | Ask a deployment admin to license it on Data sources; the page says so within a minute |
