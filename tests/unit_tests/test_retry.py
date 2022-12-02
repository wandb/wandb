"""retry tests"""

import datetime
from unittest import mock

import pytest
from wandb.sdk.lib import retry
from requests import HTTPError


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


def test_retry_respects_time_limit():
    func = mock.Mock()
    func.side_effect = ValueError

    t0 = datetime.datetime.now()

    now = t0

    def mock_datetime_now():
        return now

    def mock_sleep(delta):
        nonlocal now
        now += datetime.timedelta(seconds=delta)

    timeout = datetime.timedelta(minutes=10)
    retrier = retry.Retry(
        func,
        retry_timedelta=timeout,
        retryable_exceptions=(ValueError,),
        sleep_fn_for_testing=mock_sleep,
        datetime_now_fn_for_testing=mock_datetime_now,
    )

    with pytest.raises(ValueError):
        retrier()

    assert timeout <= now - t0 <= 2 * timeout


def test_retry_calls_callback_on_retry_loop_start_if_http_error():
    func = mock.Mock()
    func.side_effect = HTTPError(response=mock.Mock(status_code=500))

    mock_callback = mock.Mock()

    retrier = retry.Retry(
        func,
        retryable_exceptions=(HTTPError,),
        num_retries=10,
        sleep_fn_for_testing=noop_sleep,
        retry_callback=mock_callback,
    )
    with pytest.raises(HTTPError):
        retrier()

    mock_callback.assert_called_once_with(500, mock.ANY)


@pytest.mark.parametrize(
    ["max_num_retries", "num_failures", "expect_log"],
    [
        (5, 0, False),
        (5, 1, False),
        (5, 2, True),
    ],
)
def test_retry_logs_on_retry_loop_start(
    max_num_retries: int, num_failures: int, expect_log: bool
):
    func = mock.Mock()
    func.side_effect = [ValueError()] * num_failures + [None]

    mock_log = mock.Mock()

    retrier = retry.Retry(
        func,
        retryable_exceptions=(ValueError,),
        num_retries=max_num_retries,
        sleep_fn_for_testing=noop_sleep,
        termlog_fn_for_testing=mock_log,
    )

    try:
        retrier()
    except ValueError:
        pass

    if expect_log:
        mock_log.assert_called_once()
    else:
        mock_log.assert_not_called()


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
