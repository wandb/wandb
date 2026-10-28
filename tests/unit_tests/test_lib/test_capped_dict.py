from __future__ import annotations

import sys
import threading
import uuid

from wandb.sdk.lib.capped_dict import CappedDict


def test_keeps_at_most_max_size_items():
    d = CappedDict(3)
    for i in range(10):
        d[str(i)] = i

    assert list(d.items()) == [("7", 7), ("8", 8), ("9", 9)]


def test_prune_skips_keys_removed_after_snapshot():
    # Simulates another thread deleting a key between the snapshot of
    # the keys and the deletion in _prune_dict.
    class StaleKeysDict(CappedDict):
        def keys(self):  # type: ignore[override]
            return ["already-removed", *super().keys()]

    d = StaleKeysDict(3)
    for i in range(3):
        super(CappedDict, d).__setitem__(str(i), i)

    d["new"] = "value"

    assert "new" in d


def test_concurrent_writes_do_not_raise():
    d = CappedDict(10)
    errors: list[KeyError] = []

    def fill() -> None:
        try:
            for _ in range(20_000):
                d[uuid.uuid4().hex] = None
        except KeyError as e:
            errors.append(e)

    # Switch threads often to make the race in _prune_dict likely.
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=fill) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old_interval)

    assert errors == []
