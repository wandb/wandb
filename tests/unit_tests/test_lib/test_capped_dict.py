from wandb.sdk.lib.capped_dict import CappedDict


def test_default_max_size():
    assert CappedDict().max_size == CappedDict.default_max_size == 50


def test_none_max_size_uses_default():
    assert CappedDict(None).max_size == 50


def test_falsy_max_size_falls_back_to_default():
    # max_size is set via ``max_size or default_max_size``, so 0 is treated
    # as "unset" and falls back to the default.
    assert CappedDict(0).max_size == 50


def test_custom_max_size():
    assert CappedDict(5).max_size == 5


def test_evicts_oldest_first():
    d = CappedDict(3)
    for key in ("a", "b", "c", "d", "e"):
        d[key] = key.upper()
    # "a" and "b" were inserted first, so they are evicted.
    assert list(d.items()) == [("c", "C"), ("d", "D"), ("e", "E")]


def test_size_never_exceeds_max():
    d = CappedDict(4)
    for i in range(100):
        d[f"k{i}"] = i
    assert len(d) == 4


def test_setting_existing_key_updates_without_eviction():
    d = CappedDict(3)
    d["a"], d["b"], d["c"] = 1, 2, 3
    d["b"] = 99
    # No key is evicted and the value is updated in place.
    assert list(d.items()) == [("a", 1), ("b", 99), ("c", 3)]


def test_update_prunes_to_max_size():
    d = CappedDict(3)
    d["a"], d["b"], d["c"] = 1, 2, 3
    d.update(e=4, f=5)
    assert len(d) == 3
    assert list(d.keys()) == ["c", "e", "f"]
