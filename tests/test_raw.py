"""The plugin's storage, read once it has registered (open-meridian 0.37.0)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import meridian
import pytest
from meridian import edge

from truefx import __main__ as plugin
from truefx import page
from truefx.declared import SAMPLE_DATA
from truefx.synthetic import HISTORY

from conftest import recorder


async def test_storage_read_once_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On an instance run as shards, storage is read once the plugin has
    registered, with the first settings, which come before `on_start`: its
    shard's own folder, read afresh when it registers again. `main()` reads
    none before Register: read then, it raises."""
    monkeypatch.setenv("MERIDIAN_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("MERIDIAN_PLUGIN_SHARDS", "2")
    monkeypatch.setattr(edge, "_serving", None)
    monkeypatch.setattr(page.HELD, "work", page.HELD.work)
    ran: dict[str, Any] = {}
    monkeypatch.setattr(meridian, "run", lambda **given: ran.update(given))
    plugin.main()
    lake = ran["roles"][0]
    recorder().bind(lake)

    monkeypatch.setattr(edge, "_serving", (1, 2))
    await lake.on_settings(SimpleNamespace(values={SAMPLE_DATA: True}))
    assert lake.store.root == tmp_path / "shard-1"
    assert (tmp_path / "shard-1" / HISTORY).is_dir()
    await lake.on_stop()

    monkeypatch.setattr(edge, "_serving", (0, 2))
    await lake.on_settings(SimpleNamespace(values={}))
    assert lake.store.root == tmp_path / "shard-0"
    assert lake.client.mode == "live"
    assert not (tmp_path / HISTORY).exists()
