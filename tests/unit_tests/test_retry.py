"""retry tests"""

from unittest import mock

import pytest

from wandb.sdk.lib import retry


def noop_sleep(_):
    pass


def test_retry_respects_num_retries():
    func = mock.Mock()
    func.side_effect = ValueError

    retrier = retry.Retry(
        func,
        num_retries=7,
        retryable_exceptions=(ValueError,),
        sleep_fn_for_testing=noop_sleep,
    )
    with pytest.raises(ValueError):
        retrier()

    assert func.call_count == 7 + 1


def test_retry_call_num_retries_overrides_default_num_retries():
    func = mock.Mock()
    func.side_effect = ValueError

    retrier = retry.Retry(
        func,
        num_retries=7,
        retryable_exceptions=(ValueError,),
        sleep_fn_for_testing=noop_sleep,
    )
    with pytest.raises(ValueError):
        retrier(num_retries=4)

    assert func.call_count == 4 + 1


def test_retry_respects_num_retries_across_multiple_calls():
    func = mock.Mock()
    func.side_effect = ValueError

    retrier = retry.Retry(
        func,
        num_retries=7,
        retryable_exceptions=(ValueError,),
        sleep_fn_for_testing=noop_sleep,
    )
    with pytest.raises(ValueError):
        retrier()
    with pytest.raises(ValueError):
        retrier()

    assert func.call_count == 2 * (7 + 1)


def test_retry_respects_retryable_exceptions():
    func = mock.Mock()
    func.side_effect = ValueError

    retrier = retry.Retry(
        func,
        retryable_exceptions=(ValueError,),
        num_retries=3,
        sleep_fn_for_testing=noop_sleep,
    )
    with pytest.raises(ValueError):
        retrier()

    assert func.call_count > 1

    func.reset_mock()
    func.side_effect = IndexError
    retrier = retry.Retry(
        func, retryable_exceptions=(ValueError,), sleep_fn_for_testing=noop_sleep
    )
    with pytest.raises(IndexError):
        retrier()

    assert func.call_count == 1
