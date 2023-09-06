# This exercises some capabilities above and beyond
# the Promises/A+ test suite
from time import sleep
from pytest import raises, fixture

from threading import Event
from promise import (
    Promise,
    is_thenable,
    promisify,
    promise_for_dict as free_promise_for_dict,
)
from concurrent.futures import Future
from threading import Thread

from .utils import assert_exception


class DelayedFulfill(Thread):
    def __init__(self, d, p, v):
        self.delay = d
        self.promise = p
        self.value = v
        Thread.__init__(self)

    def run(self):
        sleep(self.delay)
        self.promise.do_resolve(self.value)


class DelayedRejection(Thread):
    def __init__(self, d, p, r):
        self.delay = d
        self.promise = p
        self.reason = r
        Thread.__init__(self)

    def run(self):
        sleep(self.delay)
        self.promise.do_reject(self.reason)


class FakeThenPromise:
    def __init__(self, raises=True):
        self.raises = raises

    def then(self, s=None, f=None):
        if self.raises:
            raise Exception("FakeThenPromise raises in 'then'")


def df(value, dtime):
    p = Promise()
    t = DelayedFulfill(dtime, p, value)
    t.start()

    return p


def dr(reason, dtime):
    p = Promise()
    t = DelayedRejection(dtime, p, reason)
    t.start()

    return p


# Static methods
def test_fulfilled():
    p = Promise.fulfilled(4)
    assert p.is_fulfilled
    assert p.get() == 4


def test_rejected():
    p = Promise.rejected(Exception("Static rejected"))
    assert p.is_rejected
    with raises(Exception) as exc_info:
        p.get()
    assert str(exc_info.value) == "Static rejected"


# Fulfill
def test_fulfill_self():
    p = Promise()
    with raises(TypeError) as excinfo:
        p.do_resolve(p)
        p.get()


# Exceptions
def test_exceptions():
    def throws(v):
        assert False

    p1 = Promise()
    p1.then(throws)
    p1.do_resolve(5)

    p2 = Promise()
    p2.catch(throws)
    p2.do_reject(Exception())

    with raises(Exception) as excinfo:
        p2.get()


def test_thrown_exceptions_have_stacktrace():
    def throws(v):
        assert False

    p3 = Promise.resolve("a").then(throws)
    with raises(AssertionError) as assert_exc:
        p3.get()

    assert assert_exc.traceback[-1].path.strpath == __file__


def test_thrown_exceptions_preserve_stacktrace():
    def throws(v):
        assert False

    def after_throws(v):
        pass

    p3 = Promise.resolve("a").then(throws).then(after_throws)
    with raises(AssertionError) as assert_exc:
        p3.get()

    assert assert_exc.traceback[-1].path.strpath == __file__


# WAIT
# def test_wait_when():
#     p1 = df(5, 0.01)
#     assert p1.is_pending
#     p1._wait()
#     assert p1.is_fulfilled


def test_wait_if():
    p1 = Promise()
    p1.do_resolve(5)
    p1._wait()
    assert p1.is_fulfilled


# def test_wait_timeout():
#     p1 = df(5, 0.1)
#     assert p1.is_pending
#     with raises(Exception) as exc_info:
#         p1._wait(timeout=0.05)
#     assert str(exc_info.value) == "Timeout"
#     assert p1.is_pending
#     p1._wait()
#     assert p1.is_fulfilled


# # GET
# def test_get_when():
#     p1 = df(5, 0.01)
#     assert p1.is_pending
#     v = p1.get()
#     assert p1.is_fulfilled
#     assert 5 == v


def test_get_if():
    p1 = Promise()
    p1.do_resolve(5)
    v = p1.get()
    assert p1.is_fulfilled
    assert 5 == v


# def test_get_timeout():
#     p1 = df(5, 0.1)
#     assert p1.is_pending
#     with raises(Exception) as exc_info:
#         p1._wait(timeout=0.05)
#     assert str(exc_info.value) == "Timeout"
#     assert p1.is_pending
#     v = p1.get()
#     assert p1.is_fulfilled
#     assert 5 == v


# Promise.all
def test_promise_all_when():
    p1 = Promise()
    p2 = Promise()
    pl = Promise.all([p1, p2])
    assert p1.is_pending
    assert p2.is_pending
    assert pl.is_pending
    p1.do_resolve(5)
    p1._wait()
    assert p1.is_fulfilled
    assert p2.is_pending
    assert pl.is_pending
    p2.do_resolve(10)
    p2._wait()
    pl._wait()
    assert p1.is_fulfilled
    assert p2.is_fulfilled
    assert pl.is_fulfilled
    assert 5 == p1.get()
    assert 10 == p2.get()
    assert 5 == pl.get()[0]
    assert 10 == pl.get()[1]


def test_promise_all_when_mixed_promises():
    p1 = Promise()
    p2 = Promise()
    pl = Promise.all([p1, 32, p2, False, True])
    assert p1.is_pending
    assert p2.is_pending
    assert pl.is_pending
    p1.do_resolve(5)
    p1._wait()
    assert p1.is_fulfilled
    assert p2.is_pending
    assert pl.is_pending
    p2.do_resolve(10)
    p2._wait()
    pl._wait()
    assert p1.is_fulfilled
    assert p2.is_fulfilled
    assert pl.is_fulfilled
    assert 5 == p1.get()
    assert 10 == p2.get()
    assert pl.get() == [5, 32, 10, False, True]


def test_promise_all_when_if_no_promises():
    pl = Promise.all([10, 32, False, True])
    assert pl.get() == [10, 32, False, True]


def test_promise_all_if():
    p1 = Promise()
    p2 = Promise()
    pd1 = Promise.all([p1, p2])
    pd2 = Promise.all([p1])
    pd3 = Promise.all([])
    pd3._wait()
    assert p1.is_pending
    assert p2.is_pending
    assert pd1.is_pending
    assert pd2.is_pending
    assert pd3.is_fulfilled
    p1.do_resolve(5)
    p1._wait()
    pd2._wait()
    assert p1.is_fulfilled
    assert p2.is_pending
    assert pd1.is_pending
    assert pd2.is_fulfilled
    p2.do_resolve(10)
    p2._wait()
    pd1._wait()
    pd2._wait()
    assert p1.is_fulfilled
    assert p2.is_fulfilled
    assert pd1.is_fulfilled
    assert pd2.is_fulfilled
    assert 5 == p1.get()
    assert 10 == p2.get()
    assert 5 == pd1.get()[0]
    assert 5 == pd2.get()[0]
    assert 10 == pd1.get()[1]
    assert [] == pd3.get()


# promise_for_dict
@fixture(params=[Promise.for_dict, free_promise_for_dict])
def promise_for_dict(request):
    return request.param


def test_dict_promise_when(promise_for_dict):
    p1 = Promise()
    p2 = Promise()
    d = {"a": p1, "b": p2}
    pd1 = promise_for_dict(d)
    pd2 = promise_for_dict({"a": p1})
    pd3 = promise_for_dict({})
    assert p1.is_pending
    assert p2.is_pending
    assert pd1.is_pending
    assert pd2.is_pending
    pd3._wait()
    assert pd3.is_fulfilled
    p1.do_resolve(5)
    p1._wait()
    pd2._wait()
    assert p1.is_fulfilled
    assert p2.is_pending
    assert pd1.is_pending
    assert pd2.is_fulfilled
    p2.do_resolve(10)
    p2._wait()
    pd1._wait()
    assert p1.is_fulfilled
    assert p2.is_fulfilled
    assert pd1.is_fulfilled
    assert pd2.is_fulfilled
    assert 5 == p1.get()
    assert 10 == p2.get()
    assert 5 == pd1.get()["a"]
    assert 5 == pd2.get()["a"]
    assert 10 == pd1.get()["b"]
    assert {} == pd3.get()


def test_dict_promise_if(promise_for_dict):
    p1 = Promise()
    p2 = Promise()
    d = {"a": p1, "b": p2}
    pd = promise_for_dict(d)
    assert p1.is_pending
    assert p2.is_pending
    assert pd.is_pending
    p1.do_resolve(5)
    p1._wait()
    assert p1.is_fulfilled
    assert p2.is_pending
    assert pd.is_pending
    p2.do_resolve(10)
    p2._wait()
    assert p1.is_fulfilled
    assert p2.is_fulfilled
    # pd._wait()
    # assert pd.is_fulfilled
    # assert 5 == p1.get()
    # assert 10 == p2.get()
    # assert 5 == pd.get()["a"]
    # assert 10 == pd.get()["b"]


def test_done():
    counter = [0]
    r = Promise()

    def inc(_):
        counter[0] += 1

    def dec(_):
        counter[0] -= 1

    def end(_):
        r.do_resolve(None)

    p = Promise()
    p.done(inc, dec)
    p.done(inc, dec)
    p.done(end)
    p.do_resolve(4)

    Promise.wait(r)
    assert counter[0] == 2

    r = Promise()

    counter = [0]
    p = Promise()
    p.done(inc, dec)
    p.done(inc, dec)
    p.done(None, end)
    p.do_reject(Exception())

    Promise.wait(r)
    assert counter[0] == -2


def test_done_all():
    counter = [0]

    def inc(_):
        counter[0] += 1

    def dec(_):
        counter[0] -= 1

    p = Promise()
    r = Promise()
    p.done_all()
    p.done_all([(inc, dec)])
    p.done_all(
        [
            (inc, dec),
            (inc, dec),
            {"success": inc, "failure": dec},
            lambda _: r.do_resolve(None),
        ]
    )
    p.do_resolve(4)
    Promise.wait(r)
    assert counter[0] == 4

    p = Promise()
    r = Promise()
    p.done_all()
    p.done_all([inc])
    p.done_all([(inc, dec)])
    p.done_all(
        [
            (inc, dec),
            {"success": inc, "failure": dec},
            (None, lambda _: r.do_resolve(None)),
        ]
    )
    p.do_reject(Exception("Uh oh!"))
    Promise.wait(r)
    assert counter[0] == 1


def test_then_all():
    p = Promise()

    handlers = [
        ((lambda x: x * x), (lambda r: 1)),
        {"success": (lambda x: x + x), "failure": (lambda r: 2)},
    ]

    results = (
        p.then_all()
        + p.then_all([lambda x: x])
        + p.then_all([(lambda x: x * x, lambda r: 1)])
        + p.then_all(handlers)
    )

    p.do_resolve(4)

    assert [r.get() for r in results] == [4, 16, 16, 8]

    p = Promise()

    handlers = [
        ((lambda x: x * x), (lambda r: 1)),
        {"success": (lambda x: x + x), "failure": (lambda r: 2)},
    ]

    results = (
        p.then_all()
        + p.then_all([(lambda x: x * x, lambda r: 1)])
        + p.then_all(handlers)
    )

    p.do_reject(Exception())

    assert [r.get() for r in results] == [1, 1, 2]


def test_do_resolve():
    p1 = Promise(lambda resolve, reject: resolve(0))
    assert p1.get() == 0
    assert p1.is_fulfilled


def test_do_resolve_fail_on_call():
    def raises(resolve, reject):
        raise Exception("Fails")

    p1 = Promise(raises)
    assert not p1.is_fulfilled
    assert str(p1.reason) == "Fails"


def test_catch():
    p1 = Promise(lambda resolve, reject: resolve(0))
    p2 = p1.then(lambda value: 1 / value).catch(lambda e: e).then(lambda e: type(e))
    assert p2.get() == ZeroDivisionError
    assert p2.is_fulfilled


def test_is_thenable_promise():
    promise = Promise()
    assert is_thenable(promise)


def test_is_thenable_then_object():
    promise = FakeThenPromise()
    assert not is_thenable(promise)


def test_is_thenable_future():
    promise = Future()
    assert is_thenable(promise)


def test_is_thenable_simple_object():
    assert not is_thenable(object())


@fixture(params=[Promise.resolve])
def resolve(request):
    return request.param


def test_resolve_promise(resolve):
    promise = Promise()
    assert resolve(promise) == promise


def test_resolve_then_object(resolve):
    promise = FakeThenPromise(raises=False)
    p = resolve(promise)
    assert isinstance(p, Promise)


def test_resolve_future(resolve):
    future = Future()
    promise = resolve(future)
    assert promise.is_pending
    future.set_result(1)
    assert promise.get() == 1
    assert promise.is_fulfilled


def test_resolve_future_rejected(resolve):
    future = Future()
    promise = resolve(future)
    assert promise.is_pending
    future.set_exception(Exception("Future rejected"))
    assert promise.is_rejected
    assert_exception(promise.reason, Exception, "Future rejected")


def test_resolve_object(resolve):
    val = object()
    promised = resolve(val)
    assert isinstance(promised, Promise)
    assert promised.get() == val


def test_resolve_promise_subclass():
    class MyPromise(Promise):
        pass

    p = Promise()
    p.do_resolve(10)
    m_p = MyPromise.resolve(p)

    assert isinstance(m_p, MyPromise)
    assert m_p.get() == p.get()


def test_promise_repr_pending():
    promise = Promise()
    assert repr(promise) == "<Promise at {} pending>".format(hex(id(promise)))


def test_promise_repr_pending():
    val = {1: 2}
    promise = Promise.fulfilled(val)
    promise._wait()
    assert repr(promise) == "<Promise at {} fulfilled with {}>".format(
        hex(id(promise)), repr(val)
    )


def test_promise_repr_fulfilled():
    val = {1: 2}
    promise = Promise.fulfilled(val)
    promise._wait()
    assert repr(promise) == "<Promise at {} fulfilled with {}>".format(
        hex(id(promise)), repr(val)
    )


def test_promise_repr_rejected():
    err = Exception("Error!")
    promise = Promise.rejected(err)
    promise._wait()
    assert repr(promise) == "<Promise at {} rejected with {}>".format(
        hex(id(promise)), repr(err)
    )


def test_promise_loop():
    def by_two(result):
        return result * 2

    def executor(resolve, reject):
        resolve(Promise.resolve(1).then(lambda v: Promise.resolve(v).then(by_two)))

    p = Promise(executor)
    assert p.get(.1) == 2


def test_resolve_future_like(resolve):
    class CustomThenable(object):
        def add_done_callback(self, f):
            f(True)

        def done(self):
            return True

        def exception(self):
            pass

        def result(self):
            return True

    instance = CustomThenable()

    promise = resolve(instance)
    assert promise.get() == True


def sum_function(a, b):
    return a + b


def test_promisify_function_resolved(resolve):
    promisified_func = promisify(sum_function)

    result = promisified_func(1, 2)
    assert isinstance(result, Promise)
    assert result.get() == 3


def test_promisify_function_rejected(resolve):
    promisified_func = promisify(sum_function)

    result = promisified_func(None, None)
    assert isinstance(result, Promise)
    with raises(Exception) as exc_info_promise:
        result.get()

    with raises(Exception) as exc_info:
        sum_function(None, None)

    assert str(exc_info_promise.value) == str(exc_info.value)


def test_promises_with_only_then():
    context = {"success": False}
    error = RuntimeError("Ooops!")
    promise1 = Promise(
        lambda resolve, reject: context.update({"promise1_reject": reject})
    )
    promise2 = promise1.then(lambda x: None)
    promise3 = promise1.then(lambda x: None)
    context["promise1_reject"](error)

    promise2._wait()
    promise3._wait()
    assert promise2.reason == error
    assert promise3.reason == error


def test_promises_promisify_still_works_but_deprecated_for_non_callables():
    x = promisify(1)
    assert isinstance(x, Promise)
    assert x.get() == 1


# def test_promise_loop():
#     values = Promise.resolve([1, None, 2])
#     def on_error(error):
#         error

#     def executor(resolve, reject):
#         resolve(Promise.resolve(values).then(lambda values: Promise.all([Promise.resolve(values[0])]).catch(on_error)))

#     p = Promise(executor)
#     assert p.get(.1) == 2
