"""The e2e's reader: a `reporting` plugin on the SDK, standing in for the
reading roles, so the lake has someone whose reads it asks this plugin for.
It holds `custody` beside `reporting` only so that it can name the
currencies it asks about by resolving their ISO codes (W3.1), and `signal`
to read and hear quotes (`reporting` reads none).

It is not the plugin, and is never built into its image: `make e2e` runs it
from this file in a container of the plugin's image, which carries the SDK,
beside the plugin on core's harness. It answers its page as JSON for the
harness's runner (`page --instance reader --level read PATH`):

  /resolve                                    the currencies' IDs, by code;
  /follow?subject=ID...                       hears prices and quotes recorded
                                              for them;
  /heard                                      what it heard;
  /prices?subject=ID[&date=D][&kind=K][&dataset=D]
                                              one read: its rows, and what it
                                              left unanswered and why;
  /quotes?subject=ID                          the latest quotes in force.

Standard library and the SDK only; every amount stays text, never a float.
"""

import asyncio
import http.server
import json
import threading
import urllib.parse

import meridian
from meridian import Interface, Page, SourceChoice
from meridian.operations import as_money
from meridian.plugin.v1 import operations_pb2 as ops

PORT = 8088
LOOP = asyncio.new_event_loop()
CODES = ("EUR", "USD", "JPY", "GBP")


def price_json(price):
    meta, money = price.meta, as_money(price.price)
    return {
        "dataset": meta.source.dataset,
        "venue_id": meta.source.venue_id,
        "row_key": meta.row_key,
        "version": meta.version,
        "business_date": meta.business_date,
        "subject": meta.subjects[0].entity_id if meta.subjects else "",
        "kind": ops.PriceKind.Name(price.kind),
        "amount": str(money.amount),
        "instrument_id": money.instrument_id,
        "currency_code": money.currency_code,
        "published": [t.at_ns for t in meta.source_times
                      if t.kind == ops.SOURCE_TIME_KIND_PUBLISHED],
        "raw": meta.raw.key,
    }


def quote_json(quote):
    meta = quote.meta
    side = lambda field: str(as_money(getattr(quote, field)).amount) if quote.HasField(field) else ""  # noqa: E731
    return {
        "dataset": meta.source.dataset,
        "row_key": meta.row_key,
        "business_date": meta.business_date,
        "bid": side("bid"),
        "ask": side("ask"),
        "sized": quote.HasField("bid_quantity") or quote.HasField("ask_quantity"),
        "raw": meta.raw.key,
    }


def unanswered_json(answer):
    return [{"subject": u.subject.entity_id, "dataset": u.dataset,
             "reason": ops.UnansweredReason.Name(u.reason)} for u in answer.unanswered]


class Reader:
    def __init__(self, plugin):
        self.plugin = plugin
        self.heard = []
        self.quotes = []
        self.following = None
        self.ids = {}

    async def resolve(self):
        for code in CODES:
            if code not in self.ids:
                found = await self.plugin.resolve_identifier(
                    identifiers=[ops.Identifier(scheme="iso4217", value=code)])
                if not found.instrument_id:
                    raise RuntimeError(f"{code} did not resolve: {found}")
                self.ids[code] = found.instrument_id
        return dict(self.ids)

    async def on_price(self, heard):
        self.heard.append(price_json(heard.message.price))

    async def on_quote(self, heard):
        self.quotes.append(quote_json(heard.message.quote))

    async def answer(self, path, query):
        one = lambda name: query.get(name, [""])[0]  # noqa: E731
        if path == "/resolve":
            return await self.resolve()
        if path == "/follow":
            if self.following is None:
                self.following = asyncio.ensure_future(
                    self.plugin.receive(prices_recorded=self.on_price,
                                        quotes_recorded=self.on_quote, subjects=query["subject"]))
            return {"following": query["subject"]}
        if path == "/datasets":
            # The lake's datasets as a reader lists them (contract v27): each
            # one's declared delay and its last liveness.
            answer = await self.plugin.list_datasets()
            return {"datasets": [
                {"dataset": d.dataset, "declared_delay_ns": d.declared_delay_ns,
                 "liveness": [item.alive_at_ns for item in d.liveness]}
                for d in answer.datasets]}
        if path == "/heard":
            return {"heard": self.heard, "quotes": self.quotes}
        if path == "/quotes":
            answer = await self.plugin.list_quotes(
                subjects=[meridian.SubjectRef(entity_id=s) for s in query["subject"]])
            return {"quotes": [quote_json(q) for q in answer.quotes],
                    "unanswered": unanswered_json(answer)}
        if path == "/prices":
            asked = {"subjects": [meridian.SubjectRef(entity_id=s) for s in query["subject"]]}
            if one("dataset"):
                asked["sources"] = SourceChoice(named=[one("dataset")])
            if one("kind"):
                asked["kinds"] = [one("kind")]
            if one("date"):
                asked["business_date"] = one("date")
            answer = await self.plugin.list_prices(**asked)
            return {"prices": [price_json(p) for p in answer.prices],
                    "unanswered": unanswered_json(answer)}
        return {"page": "the e2e's reader"}


def serve(reader):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            asked = reader.answer(parsed.path, urllib.parse.parse_qs(parsed.query))
            future = asyncio.run_coroutine_threadsafe(asked, LOOP)
            try:
                body, status = json.dumps(future.result(timeout=60), sort_keys=True), 200
            except Exception as failed:  # said on the page, for the run to quote
                body, status = json.dumps({"failed": f"{type(failed).__name__}: {failed}"}), 500
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


#: What the stand-in registers, its whole declaration (contract v25): the
#: e2e prints it with meridian-declaration and the harness holds the
#: stand-in's registration to it.
DECLARATION = meridian.Declaration(
    interface=Interface(PORT, "The e2e's reader",
                        pages=[Page("/", "Prices", levels=["read"], roles=["reporting"])]),
)


async def main():
    # Contract v25: what the stand-in registers is its declaration.
    plugin = await meridian.connect(declaration=DECLARATION)
    reader = Reader(plugin)
    threading.Thread(target=serve, args=(reader,), daemon=True).start()
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.set_event_loop(LOOP)
    LOOP.run_until_complete(main())
