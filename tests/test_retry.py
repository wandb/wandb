import pytest
import datetime

from wandb import retry


class FailException(Exception):
    pass


def fail_for_n_function(n):
    call_num = [0]  # use a list so we can modify in this scope

    def fn(an_arg):
        print(an_arg)
        try:
            if call_num[0] < n:
                raise FailException('Failed at call_num: %s' % call_num)
        finally:
            call_num[0] += 1
        return True
    return fn


def test_fail_for_n_function():
    failing_fn = fail_for_n_function(3)
    with pytest.raises(FailException):
        failing_fn('hello')
    with pytest.raises(FailException):
        failing_fn('hello')
    with pytest.raises(FailException):
        failing_fn('hello')
    assert failing_fn('hello')


def test_retry_with_success():
    failing_fn = fail_for_n_function(3)
    fn = retry.Retry(failing_fn, FailException)
    fn('hello', retry_timedelta=datetime.timedelta(days=1), retry_sleep_base=0.001)
    assert fn.num_iters == 3


def test_retry_with_timeout():
    failing_fn = fail_for_n_function(10000)
    fn = retry.Retry(failing_fn, FailException)
    with pytest.raises(FailException):
        fn('hello', retry_timedelta=datetime.timedelta(
            0, 0, 0, 50), retry_sleep_base=0.001)
