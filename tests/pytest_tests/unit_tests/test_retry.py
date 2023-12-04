"""retry tests."""

import asyncio
import dataclasses
import datetime
from typing import Iterator
from unittest import mock

import pytest
from wandb.sdk.lib import retry


@dataclasses.dataclass
class MockTime:
    now: datetime.datetime
    sleep: mock.Mock
    sleep_async: mock.Mock


@pytest.fixture(autouse=True)
def mock_time() -> Iterator[MockTime]:
    """Mock out the now()/sleep() funcs used by the retry logic."""
    now = datetime.datetime.now()

    def _sleep(seconds):
        nonlocal now
        now += datetime.timedelta(seconds=seconds)

    async def _sleep_async(seconds):
        nonlocal now
        now += datetime.timedelta(seconds=seconds)
        await asyncio.sleep(1e-9)  # let the event loop shuffle stuff around

    with mock.patch(
        "wandb.sdk.lib.retry.NOW_FN",
        wraps=lambda: now,
    ) as mock_now, mock.patch(
        "wandb.sdk.lib.retry.SLEEP_FN", side_effect=_sleep
    ) as mock_sleep, mock.patch(
        "wandb.sdk.lib.retry.SLEEP_ASYNC_FN", side_effect=_sleep_async
    ) as mock_sleep_async:
        yield MockTime(now=mock_now, sleep=mock_sleep, sleep_async=mock_sleep_async)


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


class MyError(Exception):
    pass


SECOND = datetime.timedelta(seconds=1)


class TestFilteredBackoff:
    def test_reraises_exc_failing_predicate(self):
        wrapped = mock.Mock(spec=retry.Backoff)
        filtered = retry.FilteredBackoff(
            filter=lambda e: False,
            wrapped=wrapped,
        )

        with pytest.raises(MyError):
            filtered.next_sleep_or_reraise(MyError("don't retry me"))

        wrapped.next_sleep_or_reraise.assert_not_called()

    def test_delegates_exc_passing_predicate(self):
        retriable_exc = MyError("retry me")
        wrapped = mock.Mock(
            spec=retry.Backoff,
            next_sleep_or_reraise=mock.Mock(return_value=123 * SECOND),
        )
        filtered = retry.FilteredBackoff(
            filter=lambda e: e == retriable_exc,
            wrapped=wrapped,
        )

        assert filtered.next_sleep_or_reraise(retriable_exc) == 123 * SECOND
        wrapped.next_sleep_or_reraise.assert_called_once_with(retriable_exc)


class TestExponentialBackoff:
    def test_respects_max_retries(self):
        backoff = retry.ExponentialBackoff(
            initial_sleep=SECOND, max_sleep=SECOND, max_retries=3
        )
        for _ in range(3):
            backoff.next_sleep_or_reraise(MyError())
        with pytest.raises(MyError):
            backoff.next_sleep_or_reraise(MyError())

    def test_respects_timeout(self, mock_time: MockTime):
        t0 = mock_time.now()
        dt = 300 * SECOND
        backoff = retry.ExponentialBackoff(
            initial_sleep=SECOND, max_sleep=10 * dt, timeout_at=t0 + dt
        )
        with pytest.raises(MyError):
            for _ in range(9999):
                mock_time.sleep(
                    backoff.next_sleep_or_reraise(MyError()).total_seconds()
                )

        assert t0 + dt <= mock_time.now() <= t0 + 2 * dt

    def test_respects_max_sleep_if_smaller_than_initial_sleep(
        self, mock_time: MockTime
    ):
        max_sleep = 10 * SECOND
        backoff = retry.ExponentialBackoff(
            initial_sleep=2 * max_sleep, max_sleep=max_sleep
        )
        assert backoff.next_sleep_or_reraise(MyError()) == max_sleep


class TestRetryAsync:
    def test_follows_backoff_schedule(self, mock_time: MockTime):
        fn = mock.Mock(side_effect=MyError("oh no"))
        with pytest.raises(MyError):
            asyncio.run(
                retry.retry_async(
                    mock.Mock(
                        spec=retry.Backoff,
                        next_sleep_or_reraise=mock.Mock(
                            side_effect=[
                                1 * SECOND,
                                2 * SECOND,
                                MyError(),
                            ]
                        ),
                    ),
                    fn,
                    "pos1",
                    "pos2",
                    kw1="kw1",
                    kw2="kw2",
                )
            )

        mock_time.sleep_async.assert_has_calls(
            [
                mock.call(1.0),
                mock.call(2.0),
            ]
        )

        fn.assert_has_calls(
            [
                mock.call("pos1", "pos2", kw1="kw1", kw2="kw2"),
                mock.call("pos1", "pos2", kw1="kw1", kw2="kw2"),
                mock.call("pos1", "pos2", kw1="kw1", kw2="kw2"),
            ]
        )

    def test_calls_on_exc(self, mock_time: MockTime):
        backoff = mock.Mock(
            spec=retry.Backoff,
            next_sleep_or_reraise=mock.Mock(return_value=1 * SECOND),
        )

        excs = [MyError("one"), MyError("two")]

        fn_sync = mock.Mock(
            side_effect=[
                *excs,
                lambda: None,
            ],
        )

        async def fn():
            return fn_sync()

        on_exc = mock.Mock()
        asyncio.run(retry.retry_async(backoff, fn, on_exc=on_exc))

        on_exc.assert_has_calls(
            [
                mock.call(excs[0]),
                mock.call(excs[1]),
            ]
        )
