# Pages

Both pages are the data role's, the same on every data plugin, under
**Manage**, for the plugin's admins. Neither shows a rate. Each is also a
read tool on the deployment's MCP, answering what the page shows, under the
same names on every data plugin. The plugin has no page or tool that
changes anything.

## Connection (`read_connection`)

How the plugin reaches TrueFX, and how its polls are going:

- **Key:** the mode (Live or Sample data), whether a TrueFX username is set
  (never its value), what TrueFX serves the session (27 pairs authenticated,
  10 without), and the session: authenticated or not, and when it opened;
- **Limits and use:** TrueFX states no limit; the plugin polls once a
  second and asks for a new session when one is lost. Its calls, the last
  call and the last error;
- **Stream:** it does not stream; TrueFX's API is polled.

## Datasets (`read_datasets`)

What the plugin serves:

- **Served:** its two datasets as the deployment's catalogue lists them,
  with the terms each declares and whether a deployment admin has licensed
  it, and what it recorded and declined and when;
- **Wants:** the wants it heard and the standing wants it keeps current,
  searched and paged; **Subjects**;
- **TrueFX:** how many pairs have both currencies resolved, the currencies
  not resolved, the days built from its polls, and the history files held,
  the months they cover and the lines that did not read.
