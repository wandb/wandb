from __future__ import annotations

import random

import pytest
from wandb.sdk.lib import runid


def test_generate_id_is_base36():
    # Given reasonable randomness assumptions, generating an 1000-digit string should
    # hit all 36 characters at least once >99.9999999999% of the time.
    new_id = runid.generate_id(1000)
    assert len(new_id) == 1000
    assert set(new_id) == set("0123456789abcdefghijklmnopqrstuvwxyz")


def test_generate_id_default_8_chars():
    assert len(runid.generate_id()) == 8


@pytest.fixture
def isolate_random_state():
    orig_state = random.getstate()
    try:
        yield
    finally:
        random.setstate(orig_state)


@pytest.mark.usefixtures("isolate_random_state")
def test_generate_fast_id_independent_of_global_seed():
    random.seed(42)
    id1 = runid.generate_fast_id(128)

    random.seed(42)
    id2 = runid.generate_fast_id(128)

    assert id1 != id2, "generate_fast_id should not be affected by global random.seed()"
