import multiprocessing as mp
import random
from concurrent.futures import ProcessPoolExecutor

from pytest import fixture, mark
from wandb.sdk.lib.runid import generate_fast_id, generate_id


def test_generate_id_is_base36():
    # Given reasonable randomness assumptions, generating an 1000-digit string should
    # hit all 36 characters at least once >99.9999999999% of the time.
    new_id = generate_id(1000)
    assert len(new_id) == 1000
    assert set(new_id) == set("0123456789abcdefghijklmnopqrstuvwxyz")


def test_generate_id_default_8_chars():
    assert len(generate_id()) == 8


@fixture
def isolate_random_state():
    """Isolate the random state to avoid affecting other tests."""
    orig_state = random.getstate()
    try:
        yield
    finally:
        random.setstate(orig_state)


@mark.usefixtures("isolate_random_state")
def test_generate_fast_id_is_independent_of_global_seed():
    random.seed(42)
    id1 = generate_fast_id(128)

    random.seed(42)
    id2 = generate_fast_id(128)

    assert id1 != id2, "generate_fast_id should not be affected by global random.seed()"


@mark.usefixtures("isolate_random_state")
@mark.parametrize(
    "start_method",
    mp.get_all_start_methods(),  # Supported start methods will be platform-dependent
)
def test_generate_fast_id_is_fork_safe(start_method: str):
    """Check that generate_fast_id doesn't produce duplicate IDs child processes.

    This can happen if `fork`-ed child processes all erroneously inherit the same
    random state from the parent process.
    """
    with ProcessPoolExecutor(2, mp.get_context(start_method)) as executor:
        generated_ids = executor.map(generate_fast_id, [128] * 2)

    assert len(set(generated_ids)) == 2
