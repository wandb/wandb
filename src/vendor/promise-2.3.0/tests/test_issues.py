# This tests reported issues in the Promise package
from concurrent.futures import ThreadPoolExecutor
from promise import Promise
import time
import weakref
import gc

executor = ThreadPoolExecutor(max_workers=40000)


def test_issue_11():
    # https://github.com/syrusakbary/promise/issues/11
    def test(x):
        def my(resolve, reject):
            if x > 0:
                resolve(x)
            else:
                reject(Exception(x))

        return Promise(my)

    promise_resolved = test(42).then(lambda x: x)
    assert promise_resolved.get() == 42

    promise_rejected = test(-42).then(lambda x: x, lambda e: str(e))
    assert promise_rejected.get() == "-42"


def identity(x, wait):
    if wait:
        time.sleep(wait)
    return x


def promise_with_wait(x, wait):
    return Promise.resolve(identity(x, wait))


def test_issue_9():
    no_wait = Promise.all(
        [promise_with_wait(x1, None).then(lambda y: x1 * y) for x1 in (0, 1, 2, 3)]
    ).get()
    wait_a_bit = Promise.all(
        [promise_with_wait(x2, 0.05).then(lambda y: x2 * y) for x2 in (0, 1, 2, 3)]
    ).get()
    wait_longer = Promise.all(
        [promise_with_wait(x3, 0.1).then(lambda y: x3 * y) for x3 in (0, 1, 2, 3)]
    ).get()

    assert no_wait == wait_a_bit
    assert no_wait == wait_longer


@Promise.safe
def test_issue_9_safe():
    no_wait = Promise.all(
        [promise_with_wait(x1, None).then(lambda y: x1 * y) for x1 in (0, 1, 2, 3)]
    ).get()
    wait_a_bit = Promise.all(
        [promise_with_wait(x2, 0.05).then(lambda y: x2 * y) for x2 in (0, 1, 2, 3)]
    ).get()
    wait_longer = Promise.all(
        [promise_with_wait(x3, 0.1).then(lambda y: x3 * y) for x3 in (0, 1, 2, 3)]
    ).get()

    assert no_wait == [0, 3, 6, 9]
    assert no_wait == wait_a_bit
    assert no_wait == wait_longer


def test_issue_26():
    context = {"success": False}
    promise1 = Promise(
        lambda resolve, reject: context.update({"promise1_reject": reject})
    )
    promise1.then(lambda x: None)
    promise1.then(lambda x: None)
    context["promise1_reject"](RuntimeError("Ooops!"))

    promise2 = Promise(
        lambda resolve, reject: context.update({"promise2_resolve": resolve})
    )
    promise3 = promise2.then(lambda x: context.update({"success": True}))
    context["promise2_resolve"](None)

    # We wait so it works in asynchronous envs
    promise3._wait(timeout=.1)
    assert context["success"]


# def promise_in_executor(x, wait):
#     return Promise.promisify(executor.submit(identity, x, wait))


# @Promise.safe
# def test_issue_9_extra():
#     no_wait = Promise.all([promise_in_executor(x1, None).then(lambda y: x1*y) for x1 in (0,1,2,3)]).get()
#     wait_a_bit = Promise.all([promise_in_executor(x2, 0.1).then(lambda y: x2*y) for x2 in (0,1,2,3)]).get()
#     wait_longer = Promise.all([promise_in_executor(x3, 0.5).then(lambda y: x3*y) for x3 in (0,1,2,3)]).get()

#     assert no_wait == [0, 3, 6, 9]
#     assert no_wait == wait_a_bit
#     assert no_wait == wait_longer


def test_issue_33():
    def do(x):
        v = Promise.resolve("ok").then(lambda x: x).get()
        return v

    p = Promise.resolve(None).then(do)
    assert p.get() == "ok"


def test_issue_75():
    def function_with_local_type():
        class A:
            pass

        a = A()
        assert a == Promise.resolve(a).get()

        return weakref.ref(A)

    weak_reference = function_with_local_type()

    # The local type 'A' from the function is still kept alive by reference cycles.
    gc.collect()

    # Now the local type should have been garbage collected,
    # such that the weak reference should be invalid.
    assert not weak_reference()
