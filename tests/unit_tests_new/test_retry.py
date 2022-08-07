"""retry tests"""

import datetime
from unittest import mock

import pytest
from wandb.sdk.lib import retry


def noop_sleep(_):
    pass


def test_retry_respects_num_retries():
    func = mock.Mock()
    func.side_effect = ValueError

    num_retries = 7
    retrier = retry.Retry(
        func,
        num_retries=num_retries,
        retryable_exceptions=(ValueError,),
        sleep_fn_for_testing=noop_sleep,
    )
    with pytest.raises(ValueError):
        retrier()

    assert func.call_count == num_retries + 1


def test_retry_call_num_retries_overrides_default_num_retries():
    func = mock.Mock()
    func.side_effect = ValueError

    retrier = retry.Retry(
        func,
        retryable_exceptions=(ValueError,),
        sleep_fn_for_testing=noop_sleep,
    )
    num_retries = 4
    with pytest.raises(ValueError):
        retrier(num_retries=num_retries)

    assert func.call_count == num_retries + 1


def test_retry_respects_num_retries_across_multiple_calls():
    func = mock.Mock()
    func.side_effect = ValueError

    num_retries = 7
    retrier = retry.Retry(
        func,
        num_retries=num_retries,
        retryable_exceptions=(ValueError,),
        sleep_fn_for_testing=noop_sleep,
    )
    with pytest.raises(ValueError):
        retrier()
    with pytest.raises(ValueError):
        retrier()

    assert func.call_count == 2 * (num_retries + 1)


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


def test_retry_respects_secondary_timeout():
    func = mock.Mock()
    func.side_effect = ValueError

    now = datetime.datetime.now()
    mock_datetime_now = mock.Mock()
    mock_datetime_now.side_effect = [
        now + datetime.timedelta(minutes=i) for i in range(30)
    ]

    def check_retry_timeout(e):
        if isinstance(e, ValueError):
            return datetime.timedelta(minutes=10)

    retry_timedelta = datetime.timedelta(hours=7)
    retrier = retry.Retry(
        func,
        retryable_exceptions=(ValueError,),
        check_retry_fn=check_retry_timeout,
        retry_timedelta=retry_timedelta,
        num_retries=10000,
        sleep_fn_for_testing=noop_sleep,
        datetime_now_fn_for_testing=mock_datetime_now,
    )
    with pytest.raises(ValueError):
        retrier()

    # add some slop for other timeout calls, should be about 10 minutes of retries
    assert 10 <= mock_datetime_now.call_count < 15
