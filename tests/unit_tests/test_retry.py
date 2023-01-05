"""retry tests"""

import dataclasses
import datetime
from typing import Iterator
from unittest import mock

import pytest
from wandb.sdk.lib import retry


@dataclasses.dataclass
class MockTime:
    now: mock.Mock
    sleep: mock.Mock


@pytest.fixture(autouse=True)
def mock_time() -> Iterator[MockTime]:
    """Mock out the now()/sleep() funcs used by the retry logic."""
    now = datetime.datetime.now()

    def _sleep(seconds):
        nonlocal now
        now += datetime.timedelta(seconds=seconds)

    with mock.patch(
        "wandb.sdk.lib.retry.NOW_FN",
        wraps=lambda: now,
    ) as mock_now, mock.patch(
        "wandb.sdk.lib.retry.SLEEP_FN", side_effect=_sleep
    ) as mock_sleep:
        yield MockTime(now=mock_now, sleep=mock_sleep)


def test_retry_respects_num_retries():
    func = mock.Mock()
    func.side_effect = ValueError

    num_retries = 7
    retrier = retry.Retry(
        func,
        num_retries=num_retries,
        retryable_exceptions=(ValueError,),
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
    )
    with pytest.raises(ValueError):
        retrier()

    assert func.call_count > 1

    func.reset_mock()
    func.side_effect = IndexError
    retrier = retry.Retry(
        func,
        retryable_exceptions=(ValueError,),
    )
    with pytest.raises(IndexError):
        retrier()

    assert func.call_count == 1


def test_retry_respects_secondary_timeout(mock_time: MockTime):
    func = mock.Mock()
    func.side_effect = ValueError

    t0 = mock_time.now()

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
    )
    with pytest.raises(ValueError):
        retrier()

    # add some slop for other timeout calls, should be about 10 minutes of retries
    assert 10 <= (mock_time.now() - t0).total_seconds() / 60 < 20
