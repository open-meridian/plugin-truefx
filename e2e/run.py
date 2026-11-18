"""`make e2e`: the plugin end to end on core's plugin harness (contracts v18
to v22), beside a reader (e2e/reader.py), never reaching TrueFX.

1. TrueFX unreachable: the plugin's hosts file sends TrueFX's address
   nowhere, so its polls fail, and Connection says so; nothing is recorded.
   The deployment admin's tool lists the two datasets, `daily` and `live`,
   each on New York's day ending at 17:00, with their modes.
2. Licensed and entitled: the admin licenses both datasets and entitles the
   reader to them; and the reader reads the euro's latest one-minute bars on
   the live dataset, which nothing has recorded, so the lake asks the
   plugin to keep them current: a standing want of bars of 60 seconds,
   which the plugin holds, recording nothing and declining nothing while no
   minute has closed (item 95).
3. Sample data on: the plugin polls the synthetic feed, three polls on
   business date 9 October 2026, which closed long ago, so the day it built
   is pushed: the close, the closing bid and offer, and the bar of each of
   the ten pairs, every currency resolved to its cash instrument first, and
   each poll's new ticks restate the pairs that moved.
4. Wanted from the history files: the reader reads the euro's close on 8
   October, which nothing has recorded; the lake asks the plugin, which
   records it from TrueFX's history file, EUR/USD's last mid that day,
   1.163925, in dollars; and the dollar's, USD/JPY's 149.380, in yen, as
   TrueFX quotes it. The yen's own instrument, which no TrueFX pair has as
   its base, is declined as not covered: nothing is inverted.
5. Pushed: the euro's close on 9 October, from the plugin's polls, each EUR
   pair's in its quote currency, published at the day's end.
6. Live: the reader follows the euro, whose latest quote stands as a want of
   the live dataset; the plugin records each EUR pair's top of book, its bid
   and offer and no size, and each poll's liveness (contract v27), which the
   reader lists beside each dataset's declared delay, none. The euro's
   minute that closed while its bars' want stood -- EUR/USD's at 16:59 New
   York on the 9th, the one minute the feed's polls heard whole -- was
   recorded once, unasked, for that want: the mid's open, high, low and
   close, 1.164535, valid over the minute, published at its end.
7. Parity: the plugin's two read tools answer through the deployment's MCP
   what its two pages show, the data role's fields under its names, the
   username not set and the session unauthenticated, each dataset licensed.
8. Its raw responses are in its granted storage, and `store lake` numbers
   each dataset's rows from 1 with no holes, the wants asked, answered and
   declined.
9. Restarted: the plugin reads back the day it built and records nothing
   twice.

Run from the repository's root by the Makefile, which builds the image,
copies the harness out and writes the plugins' compose file first, and
exports what the compose files read. Standard library only.
"""

import json
import subprocess
import sys
import time

VENDOR = "truefx"
LOG = ".e2e/runner.log"
COMPOSE = ["docker", "compose", "-p", f"{VENDOR}-e2e", "-f", ".e2e/harness/compose.yaml",
           "-f", ".e2e/harness/plugins.yaml", "-f", "e2e/plugin.yaml"]
DAILY, LIVE = f"{VENDOR}:daily", f"{VENDOR}:live"
#: The synthetic feed's ten pairs, and what the plugin records of them.
PAIRS = ["AUDUSD", "EURCHF", "EURGBP", "EURJPY", "EURUSD", "GBPJPY", "GBPUSD", "USDCAD",
         "USDCHF", "USDJPY"]
#: 9 October 2026 ended at 17:00 New York, 21:00 UTC.
CLOSED_9TH_NS = 1791579600 * 10**9
#: A minute bar's length, and the 9th's last minute, 16:59 New York, which
#: the feed's third poll fell in: its first millisecond.
MINUTE_NS = 60 * 10**9
MINUTE_9TH_MS = 1791579540000


class Failed(Exception):
    pass


def log(text):
    with open(LOG, "a", encoding="utf-8") as kept:
        kept.write(text + "\n")


def compose(*args, check=True):
    done = subprocess.run(COMPOSE + list(args), capture_output=True, text=True, timeout=600)
    log(f"$ compose {' '.join(args)[:300]}\n{done.stdout[-4000:]}{done.stderr[-2000:]}")
    if check and done.returncode != 0:
        raise Failed(f"compose {' '.join(args)[:200]}: {(done.stdout + done.stderr).strip()[-600:]}")
    return done


def runner(*args, check=True):
    done = compose("run", "--rm", "-T", "runner", *args, check=check)
    return done.stdout if check else done


def must(condition, why):
    if not condition:
        raise Failed(why)


def until(seconds, attempt, what):
    deadline = time.monotonic() + seconds
    last = None
    while True:
        try:
            answer = attempt()
        except Failed as failed:
            answer, last = None, failed
        if answer:
            return answer
        if time.monotonic() > deadline:
            raise Failed(f"{what}, in {seconds} seconds" + (f": {last}" if last else ""))
        time.sleep(2)


def page(instance, level, path):
    said = runner("page", "--instance", instance, "--level", level, path)
    status, _, body = said.partition("\n")
    must(status.strip() == "200", f"{instance} {path} answered {said[-600:]}")
    return body


def read(path):
    return json.loads(page("reader", "read", path))


def call(tool, arguments=None):
    done = runner("mcp", "call", tool, json.dumps(arguments or {}), check=False)
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        raise Failed(f"{tool}: no answer: {(done.stdout + done.stderr)[-400:]}") from None
    must(answer.get("outcome") in ("read", "unchanged"), f"{tool} answered {done.stdout[-700:]}")
    return answer["data"]


def store_lake(codes):
    lines = compose("run", "--rm", "-T", "store", "lake").stdout.strip().splitlines()
    for instrument_id, code in codes.items():
        lines = [line.replace(instrument_id, code) for line in lines]
    return lines


def rows_of(lines, dataset):
    return [line.split("|") for line in lines if line.startswith(f"row|{dataset}|")]


def run():
    started = time.time()
    compose("--profile", "runner", "down", "-v", "--remove-orphans", check=False)
    compose("up", "-d")
    for instance in (VENDOR, "reader"):
        runner("ready", "--instance", instance)
    runner("grant", "--instance", "reader", "--level", "read", "--role", "reporting")
    runner("grant", "--instance", VENDOR, "--level", "admin")
    runner("mcp", "connect", "--covers", "deployment_admin", "--covers", f"{VENDOR}:admin")
    tools = runner("mcp", "list").split()
    named = {t.rsplit("__", 1)[-1]: t for t in tools}
    for name in ("list_datasets", "read_connection", "read_datasets"):
        must(name in named, f"step 1, {name} is listed: {tools}")

    # 1. TrueFX unreachable: said on Connection, nothing recorded; and the
    #    catalogue as the deployment admin's tool lists it.
    runner("page", "--instance", VENDOR, "--level", "admin", "/", "--until", "URLError",
           "--seconds", "90")
    connection = call(named["read_connection"])
    must(connection["mode"] == "Live" and connection["calls"] > 0
         and connection["last_error"].startswith("URLError") and not connection["healthy"],
         f"step 1, read_connection says TrueFX does not answer: {connection}")
    must(not rows_of(store_lake({}), DAILY), "step 1, nothing recorded while unreachable")
    held = until(60, lambda: {d["dataset"]: d for d in call(named["list_datasets"])["datasets"]
                              if d["dataset"] in (DAILY, LIVE)} or None,
                 "step 1, the datasets were not listed")
    must(set(held) == {DAILY, LIVE}, f"step 1, the two datasets: {held}")
    for dataset, modes in ((DAILY, ["pull", "push"]), (LIVE, ["pull", "stream"])):
        entry = held[dataset]["catalogue_entry"]
        must(entry["modes"] == modes and entry["day_time_zone"] == "America/New_York"
             and entry["day_end_minute"] == 1020, f"step 1, {dataset}'s entry: {entry}")

    # 2. Licensed and entitled; the euro's one-minute bars on the live
    #    dataset wanted, kept current from the next minute closed.
    runner("licence", DAILY, "kept=true", "retention_days=0", "derived_use=true", "display=true",
           "personal_use=false", "note=TrueFX's daily closes and bars.")
    runner("licence", LIVE, "kept=true", "retention_days=2", "display=true",
           "personal_use=false", "note=Kept two days.")
    runner("grant", "--instance", "reader", "--level", "read", "--role", "signal")
    for dataset in (DAILY, LIVE):
        runner("entitle", "--instance", "reader", dataset, "note=The e2e's reader.")
    ids = read("/resolve")
    codes = {instrument_id: code for code, instrument_id in ids.items()}
    bars_asked = f"/bars?subject={ids['EUR']}&interval={MINUTE_NS}&dataset={LIVE}"
    asked = read(bars_asked)
    must(not asked["bars"], f"step 2, no bar recorded yet: {asked}")
    until(60, lambda: call(named["read_datasets"])["standing_wants"] >= 1 or None,
          "step 2, the plugin did not hold the euro's bars' standing want")
    lines = store_lake(codes)
    must(any(line.startswith(f"want|{LIVE}|asked|EUR") for line in lines)
         and not any(line.startswith(f"want|{LIVE}|declined") for line in lines),
         f"step 2, the euro's bars asked of the live dataset, nothing declined: {lines}")

    # 3. Sample data: the synthetic feed polled, 9 October built and pushed.
    runner("settings", "--instance", VENDOR, "sample_data=true")

    # Each poll's new ticks restate the closed day: EUR/USD moved in all
    # three polls, so its rows reach version 3; USD/JPY's 2; the rest 1.
    def pushed():
        rows = rows_of(store_lake(codes), DAILY)
        versions = {row[4]: int(row[5]) for row in rows}
        return rows if versions.get("EURUSD:close:2026-10-09") == 3 else None
    rows = until(120, pushed, "step 3, the 9th's days were not pushed and restated")
    latest = {}
    for row in rows:
        latest[row[4]] = max(latest.get(row[4], 0), int(row[5]))
    expected = sorted(f"{pair}:{what}:2026-10-09" for pair in PAIRS
                      for what in ("close", "bid", "ask", "1d"))
    must(sorted(latest) == expected, f"step 3, each pair's close, bid, ask and bar: {latest}")
    must({k: v for k, v in latest.items() if v != 1} == {
        **{f"EURUSD:{w}:2026-10-09": 3 for w in ("close", "bid", "ask", "1d")},
        **{f"USDJPY:{w}:2026-10-09": 2 for w in ("close", "bid", "ask", "1d")}},
         f"step 3, restated as the polls' ticks came: {latest}")
    must(all(row[9] == "2026-10-09" and row[8] == "" for row in rows),
         f"step 3, each row on its business date, no venue: {rows}")
    eurusd = next(row for row in rows if row[4] == "EURUSD:close:2026-10-09")
    must(eurusd[6] == "EUR", f"step 3, EUR/USD's close is the euro's: {eurusd}")

    # 4. Wanted: the 8th, from the history files; the yen declined.
    def close(code, day, count=1):
        asked = f"/prices?subject={ids[code]}&date={day}&kind=close&dataset={DAILY}"
        read(asked)
        return until(90, lambda: (lambda r: r if len(r) >= count else None)(read(asked)["prices"]),
                     f"step 4, {code}'s close on {day} was not recorded")
    [euro] = close("EUR", "2026-10-08")
    must(euro["row_key"] == "EURUSD:close:2026-10-08" and euro["amount"] == "1.163925"
         and euro["instrument_id"] == ids["USD"] and euro["kind"] == "PRICE_KIND_CLOSE"
         and euro["business_date"] == "2026-10-08" and euro["version"] == 1
         and euro["raw"] == "synthetic/history/EURUSD-2026-10.csv#29"
         and euro["published"] == [1791493200 * 10**9],
         f"step 4, the euro in dollars, as TrueFX's file states it: {euro}")
    [dollar] = close("USD", "2026-10-08")
    must(dollar["row_key"] == "USDJPY:close:2026-10-08" and dollar["amount"] == "149.380"
         and dollar["instrument_id"] == ids["JPY"],
         f"step 4, the dollar in yen, never inverted: {dollar}")
    read(f"/prices?subject={ids['JPY']}&date=2026-10-08&kind=close&dataset={DAILY}")
    until(90, lambda: any(line.startswith(f"want|{DAILY}|declined|JPY|")
                          for line in store_lake(codes)),
          "step 4, the yen's own instrument was not declined")
    declined = [line for line in store_lake(codes) if line.startswith(f"want|{DAILY}|declined|JPY|")]
    # UnansweredReason's number: 2 is UNANSWERED_REASON_NOT_COVERED.
    must(declined[0].endswith("|2"), f"step 4, declined as not covered: {declined}")

    # 5. Pushed: the 9th's closes, each EUR pair's, published at the day's end.
    closes = {p["row_key"]: p for p in close("EUR", "2026-10-09", count=4)}
    must(sorted(closes) == ["EURCHF:close:2026-10-09", "EURGBP:close:2026-10-09",
                            "EURJPY:close:2026-10-09", "EURUSD:close:2026-10-09"],
         f"step 5, each EUR pair's close: {sorted(closes)}")
    pushed_close = closes["EURUSD:close:2026-10-09"]
    must(pushed_close["amount"] == "1.164535" and pushed_close["version"] == 3
         and pushed_close["published"] == [CLOSED_9TH_NS]
         and pushed_close["raw"].startswith("responses/"),
         f"step 5, EUR/USD's last mid on the 9th, from the polls: {pushed_close}")
    must(closes["EURJPY:close:2026-10-09"]["instrument_id"] == ids["JPY"]
         and closes["EURGBP:close:2026-10-09"]["instrument_id"] == ids["GBP"],
         f"step 5, each in its quote currency: {closes}")

    # 6. Live: the euro followed, its latest quotes kept current.
    read(f"/follow?subject={ids['EUR']}")

    def quotes():
        held = {q["row_key"].split(":")[0]: q for q in read(f"/quotes?subject={ids['EUR']}")["quotes"]}
        return held if {"EURUSD", "EURGBP", "EURJPY", "EURCHF"} <= set(held) else None
    latest = until(120, quotes, "step 6, the euro's quotes were not recorded")
    eur_usd = latest["EURUSD"]
    must((eur_usd["bid"], eur_usd["ask"]) == ("1.16452", "1.16455") and not eur_usd["sized"]
         and eur_usd["dataset"] == LIVE and not eur_usd["business_date"]
         and eur_usd["row_key"] == "EURUSD:q:1791579598512",
         f"step 6, EUR/USD's top of book as TrueFX stated it, no size: {eur_usd}")

    def alive():
        listed = {d["dataset"]: d for d in read("/datasets")["datasets"]}
        return listed if listed.get(LIVE, {}).get("liveness") else None
    listed = until(60, alive, "step 6, the live dataset's liveness was not recorded")
    must(all(listed[d]["declared_delay_ns"] == 0 for d in (DAILY, LIVE))
         and max(listed[LIVE]["liveness"]) > 0 and not listed[DAILY]["liveness"],
         f"step 6, the live dataset alive, no delay declared: {listed}")

    # 6. The euro's minute bars, kept current: EUR/USD's minute closed while
    #    the want stood, recorded once, unasked.
    [bar] = until(60, lambda: read(bars_asked)["bars"] or None,
                  "step 6, the euro's minute bar was not recorded")
    must(bar["row_key"] == f"EURUSD:1m:{MINUTE_9TH_MS}" and bar["dataset"] == LIVE
         and [bar[f] for f in ("open", "high", "low", "close")] == ["1.164535"] * 4
         and bar["instrument_id"] == ids["USD"] and bar["volume"] == "0"
         and bar["valid_until_ns"] - bar["valid_from_ns"] == MINUTE_NS
         and bar["valid_until_ns"] == CLOSED_9TH_NS and bar["published"] == [CLOSED_9TH_NS]
         and not bar["business_date"] and bar["version"] == 1
         and bar["raw"].startswith("responses/"),
         f"step 6, EUR/USD's minute of the mid, as polled: {bar}")
    minute_rows = [row for row in rows_of(store_lake(codes), LIVE) if row[2] == "bar"]
    must([(row[4], row[5], row[7]) for row in minute_rows]
         == [(f"EURUSD:1m:{MINUTE_9TH_MS}", "1", str(MINUTE_NS))],
         f"step 6, one minute bar in the live dataset, recorded once: {minute_rows}")

    # 7. Parity.
    connection = call(named["read_connection"])
    must(connection["mode"] == "Sample data" and connection["session"] == "Unauthenticated"
         and connection["credentials"] == [{"label": "TrueFX username", "set": False}]
         and connection["sessions"] is None and connection["entitled_at_vendor"]
         == "10 pairs, unauthenticated" and connection["calls"] > 0,
         f"step 7, read_connection: {connection}")
    shown = page(VENDOR, "admin", "/")
    must("Sample data: the plugin answers from recorded responses" in shown
         and "TrueFX username: not set" in shown and "Does not stream" in shown,
         "step 7, the Connection page shows the same")

    def licensed():
        served = call(named["read_datasets"])
        return served if all(d["licensed"] for d in served["served"]) else None
    served = until(90, licensed, "step 7, read_datasets did not say each dataset licensed")
    must([d["dataset"] for d in served["served"]] == [DAILY, LIVE]
         and served["pairs_resolved"] == 10 and served["history_files"] == 3
         and served["reads_instruments"] is True
         and served["served"][0]["recorded"] >= 4 * len(PAIRS),
         f"step 7, read_datasets: {served}")
    shown = page(VENDOR, "admin", "/datasets")
    must("Not licensed yet" not in shown and "10 of 10 pairs resolved." in shown
         and "3 history files, 2026-10." in shown, "step 7, the Datasets page shows the same")

    # 8. Raw responses kept, and the lake's record.
    kept = compose("exec", "-T", VENDOR, "python", "-c",
                   "from meridian import edge; "
                   "print(sum(1 for p in (edge.storage_dir() / 'responses').rglob('*.jsonl')))")
    must(int(kept.stdout.strip() or 0) >= 1, f"step 8, raw responses in storage: {kept.stdout}")
    lines = store_lake(codes)
    log("store lake:\n" + "\n".join(lines))
    for dataset in (DAILY, LIVE):
        sequences = sorted(int(row[3]) for row in rows_of(lines, dataset))
        must(sequences and sequences == list(range(1, len(sequences) + 1)),
             f"step 8, {dataset}'s rows numbered from 1 with no holes: {sequences}")
    must(any(line.startswith(f"want|{DAILY}|answered|EUR") for line in lines),
         f"step 8, the euro's want answered: {lines}")
    must(any(line.startswith(f"row|{LIVE}|quote|") for line in lines),
         f"step 8, the quotes kept in the live dataset: {lines}")
    daily_before = sorted("|".join(row) for row in rows_of(lines, DAILY))

    # 9. Restarted: the day it built read back; nothing recorded twice.
    compose("restart", VENDOR)
    runner("ready", "--instance", VENDOR)
    until(120, lambda: call(named["read_connection"])["calls"] >= 3 or None,
          "step 9, the restarted plugin did not poll again")
    time.sleep(5)
    daily_after = sorted("|".join(row) for row in rows_of(store_lake(codes), DAILY))
    must(daily_after == daily_before,
         f"step 9, nothing recorded twice: {sorted(set(daily_after) - set(daily_before))[:6]}")

    print(f"e2e OK in {int(time.time() - started)}s: on core's plugin harness, TrueFX unreachable "
          "said on Connection with nothing recorded; the daily and live datasets listed by the "
          "deployment admin's tool on New York's day ending at 17:00; licensed and entitled, the "
          "euro's one-minute bars on live wanted and kept current; sample data's three polls "
          "built 9 October and pushed each of the ten pairs' close, closing bid and offer and "
          "bar, every currency resolved; the euro's close on 8 October "
          "wanted and recorded from TrueFX's history file (1.163925 in dollars) and the "
          "dollar's in yen (149.380), the yen's own instrument declined as not covered; each "
          "EUR pair's close on the 9th, published at the day's end; the euro followed and each "
          "EUR pair's top of book recorded as a quote with no size, and EUR/USD's minute closed "
          "while the want stood recorded once as a bar of the mid; read_connection and "
          "read_datasets answering what the pages show; raw responses in storage; `store lake` "
          "numbering each dataset's rows with no holes; and restarted, nothing recorded twice")


def main():
    open(LOG, "w").close()
    try:
        run()
    except (Failed, subprocess.TimeoutExpired, KeyError, ValueError, IndexError, StopIteration,
            TypeError) as failed:
        print(f"e2e FAILED: {failed}; the run is in {LOG}, the components' logs in "
              ".e2e/components.log", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
