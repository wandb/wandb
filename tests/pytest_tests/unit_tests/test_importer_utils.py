import sys

import pytest

pytest.mark.skipif(sys.version_info < (3, 8), reason="Requires py38+")

from wandb.apis.importers.internals.util import for_each, parallelize


def test_parallelize():
    def safe_func(x):
        return x + 1

    result = set(parallelize(safe_func, [1, 2, 3]))
    expected = set([2, 3, 4])

    assert result == expected

    def unsafe_func(x):
        if x > 2:
            raise Exception("test")
        return x

    result = set(parallelize(unsafe_func, [1, 2, 3]))
    expected = set([1, 2, None])

    assert result == expected


def test_for_each():
    def safe_func(x):
        return x + 1

    result = set(for_each(safe_func, [1, 2, 3]))
    expected = set([2, 3, 4])
    assert result == expected

    result = set(for_each(safe_func, [1, 2, 3], parallel=True))
    expected = set([2, 3, 4])
    assert result == expected

    def unsafe_func(x):
        if x > 2:
            raise Exception("test")
        return x

    result = set(for_each(unsafe_func, [1, 2, 3]))
    expected = set([1, 2, None])
    assert result == expected

    result = set(for_each(unsafe_func, [1, 2, 3], parallel=True))
    expected = set([1, 2, None])
    assert result == expected


def test_nothing():
    pass
