from pytest import raises

from promise import Promise
from promise.promise_list import PromiseList


def all(promises):
    return PromiseList(promises, Promise).promise


def test_empty_promises():
    all_promises = all([])
    assert all_promises.get() == []


def test_bad_promises():
    all_promises = all(None)

    with raises(Exception) as exc_info:
        all_promises.get()

    assert str(exc_info.value) == "PromiseList requires an iterable. Received None."


def test_promise_basic():
    all_promises = all([1, 2])
    assert all_promises.get() == [1, 2]


def test_promise_mixed():
    all_promises = all([1, 2, Promise.resolve(3)])
    assert all_promises.get() == [1, 2, 3]


def test_promise_rejected():
    e = Exception("Error")
    all_promises = all([1, 2, Promise.reject(e)])

    with raises(Exception) as exc_info:
        all_promises.get()

    assert str(exc_info.value) == "Error"


def test_promise_reject_skip_all_other_values():
    e1 = Exception("Error1")
    e2 = Exception("Error2")
    p = Promise()
    all_promises = all([1, Promise.reject(e1), Promise.reject(e2)])

    with raises(Exception) as exc_info:
        all_promises.get()

    assert str(exc_info.value) == "Error1"


def test_promise_lazy_promise():
    p = Promise()
    all_promises = all([1, 2, p])
    assert not all_promises.is_fulfilled
    p.do_resolve(3)
    assert all_promises.get() == [1, 2, 3]


def test_promise_contained_promise():
    p = Promise()
    all_promises = all([1, 2, Promise.resolve(None).then(lambda v: p)])
    assert not all_promises.is_fulfilled
    p.do_resolve(3)
    assert all_promises.get() == [1, 2, 3]
