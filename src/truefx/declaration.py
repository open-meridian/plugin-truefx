"""What this version declares beside its role (W8.1, W4.1): from contract
v25 the whole of what it says about itself.

Built from the plugin's code and used twice: `__main__` registers with it,
and `meridian plugin upload` reads the same one from the built image
(pyproject.toml's `[tool.meridian] declaration`), with the documentation's
texts beside it. A version registers exactly the declaration it was uploaded
with, or its sidecar refuses it naming the first difference, so beside the
parts it declared before (declared.py, whose docstring says what each is:
its catalogue, its storage and its settings) it carries its interface -- its
two pages, with the levels each serves, and the tools their routes make --
on a port fixed here, never read from the environment, and the vendor's
documentation, the Markdown in `docs/` (`/plugin/docs` in its image), which
a deployment admin reads on its Documentation tab before launching it.
"""

from __future__ import annotations

import meridian
from meridian import Declaration, Storage

from .declared import CATALOGUE, RESPONSES_KIND, Config
from .page import TITLE, pages

#: The port its pages are served on, on loopback, where its sidecar forwards.
PORT = 8000

DECLARATION = Declaration(
    # The settings as declared, untyped, so `meridian.run` delivers them with
    # the storage kind's window settings beside them, which a typed delivery
    # leaves out on open-meridian 0.35.1: drop after SDK 0.35.2.
    settings=Config.declared(),  # type: ignore[attr-defined]
    storage=Storage(kinds=[RESPONSES_KIND]),
    catalogue=CATALOGUE,
    interface=meridian.Interface(port=PORT, title=TITLE, pages=pages),
    documentation="docs",
)
