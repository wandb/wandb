# Tests the spec based on:
# https://github.com/promises-aplus/promises-tests

from promise import Promise
from .utils import assert_exception

from threading import Event


class Counter:
    """
    A helper class with some side effects
    we can test.
    """

    def __init__(self):
        self.count = 0

    def tick(self):
        self.count += 1

    def value(self):
        return self.count


def test_3_2_1():
    """
    Test that the arguments to 'then' are optional.
    """

    p1 = Promise()
    p2 = p1.then()
    p3 = Promise()
    p4 = p3.then()
    p1.do_resolve(5)
    p3.do_reject(Exception("How dare you!"))


def test_3_2_1_1():
    """
    That that the first argument to 'then' is ignored if it
    is not a function.
    """
    results = {}
    nonFunctions = [None, False, 5, {}, []]

    def testNonFunction(nonFunction):
        def foo(k, r):
            results[k] = r

        p1 = Promise.reject(Exception("Error: " + str(nonFunction)))
        p2 = p1.then(nonFunction, lambda r: foo(str(nonFunction), r))
        p2._wait()

    for v in nonFunctions:
        testNonFunction(v)

    for v in nonFunctions:
        assert_exception(results[str(v)], Exception, "Error: " + str(v))


def test_3_2_1_2():
    """
    That that the second argument to 'then' is ignored if it
    is not a function.
    """
    results = {}
    nonFunctions = [None, False, 5, {}, []]

    def testNonFunction(nonFunction):
        def foo(k, r):
            results[k] = r

        p1 = Promise.resolve("Error: " + str(nonFunction))
        p2 = p1.then(lambda r: foo(str(nonFunction), r), nonFunction)
        p2._wait()

    for v in nonFunctions:
        testNonFunction(v)

    for v in nonFunctions:
        assert "Error: " + str(v) == results[str(v)]


def test_3_2_2_1():
    """
    The first argument to 'then' must be called when a promise is
    fulfilled.
    """

    c = Counter()

    def check(v, c):
        assert v == 5
        c.tick()

    p1 = Promise.resolve(5)
    p2 = p1.then(lambda v: check(v, c))
    p2._wait()
    assert 1 == c.value()


def test_3_2_2_2():
    """
    Make sure callbacks are never called more than once.
    """

    c = Counter()
    p1 = Promise.resolve(5)
    p2 = p1.then(lambda v: c.tick())
    p2._wait()
    try:
        # I throw an exception
        p1.do_resolve(5)
        assert False  # Should not get here!
    except AssertionError:
        # This is expected
        pass
    assert 1 == c.value()


def test_3_2_2_3():
    """
    Make sure fulfilled callback never called if promise is rejected
    """

    cf = Counter()
    cr = Counter()
    p1 = Promise.reject(Exception("Error"))
    p2 = p1.then(lambda v: cf.tick(), lambda r: cr.tick())
    p2._wait()
    assert 0 == cf.value()
    assert 1 == cr.value()


def test_3_2_3_1():
    """
    The second argument to 'then' must be called when a promise is
    rejected.
    """

    c = Counter()

    def check(r, c):
        assert_exception(r, Exception, "Error")
        c.tick()

    p1 = Promise.reject(Exception("Error"))
    p2 = p1.then(None, lambda r: check(r, c))
    p2._wait()
    assert 1 == c.value()


def test_3_2_3_2():
    """
    Make sure callbacks are never called more than once.
    """

    c = Counter()
    p1 = Promise.reject(Exception("Error"))
    p2 = p1.then(None, lambda v: c.tick())
    p2._wait()
    try:
        # I throw an exception
        p1.do_reject(Exception("Error"))
        assert False  # Should not get here!
    except AssertionError:
        # This is expected
        pass
    assert 1 == c.value()


def test_3_2_3_3():
    """
    Make sure rejected callback never called if promise is fulfilled
    """

    cf = Counter()
    cr = Counter()
    p1 = Promise.resolve(5)
    p2 = p1.then(lambda v: cf.tick(), lambda r: cr.tick())
    p2._wait()
    assert 0 == cr.value()
    assert 1 == cf.value()


def test_3_2_5_1_when():
    """
    Then can be called multiple times on the same promise
    and callbacks must be called in the order of the
    then calls.
    """

    def add(l, v):
        l.append(v)

    p1 = Promise.resolve(2)
    order = []
    p2 = p1.then(lambda v: add(order, "p2"))
    p3 = p1.then(lambda v: add(order, "p3"))
    p2._wait()
    p3._wait()
    assert 2 == len(order)
    assert "p2" == order[0]
    assert "p3" == order[1]


def test_3_2_5_1_if():
    """
    Then can be called multiple times on the same promise
    and callbacks must be called in the order of the
    then calls.
    """

    def add(l, v):
        l.append(v)

    p1 = Promise.resolve(2)
    order = []
    p2 = p1.then(lambda v: add(order, "p2"))
    p3 = p1.then(lambda v: add(order, "p3"))
    p2._wait()
    p3._wait()
    assert 2 == len(order)
    assert "p2" == order[0]
    assert "p3" == order[1]


def test_3_2_5_2_when():
    """
    Then can be called multiple times on the same promise
    and callbacks must be called in the order of the
    then calls.
    """

    def add(l, v):
        l.append(v)

    p1 = Promise.reject(Exception("Error"))
    order = []
    p2 = p1.then(None, lambda v: add(order, "p2"))
    p3 = p1.then(None, lambda v: add(order, "p3"))
    p2._wait()
    p3._wait()
    assert 2 == len(order)
    assert "p2" == order[0]
    assert "p3" == order[1]


def test_3_2_5_2_if():
    """
    Then can be called multiple times on the same promise
    and callbacks must be called in the order of the
    then calls.
    """

    def add(l, v):
        l.append(v)

    p1 = Promise.reject(Exception("Error"))
    order = []
    p2 = p1.then(None, lambda v: add(order, "p2"))
    p3 = p1.then(None, lambda v: add(order, "p3"))
    p2._wait()
    p3._wait()
    assert 2 == len(order)
    assert "p2" == order[0]
    assert "p3" == order[1]


def test_3_2_6_1():
    """
    Promises returned by then must be fulfilled when the promise
    they are chained from is fulfilled IF the fulfillment value
    is not a promise.
    """

    p1 = Promise.resolve(5)
    pf = p1.then(lambda v: v * v)
    assert pf.get() == 25

    p2 = Promise.reject(Exception("Error"))
    pr = p2.then(None, lambda r: 5)
    assert 5 == pr.get()


def test_3_2_6_2_when():
    """
    Promises returned by then must be rejected when any of their
    callbacks throw an exception.
    """

    def fail(v):
        raise AssertionError("Exception Message")

    p1 = Promise.resolve(5)
    pf = p1.then(fail)
    pf._wait()
    assert pf.is_rejected
    assert_exception(pf.reason, AssertionError, "Exception Message")

    p2 = Promise.reject(Exception("Error"))
    pr = p2.then(None, fail)
    pr._wait()
    assert pr.is_rejected
    assert_exception(pr.reason, AssertionError, "Exception Message")


def test_3_2_6_2_if():
    """
    Promises returned by then must be rejected when any of their
    callbacks throw an exception.
    """

    def fail(v):
        raise AssertionError("Exception Message")

    p1 = Promise.resolve(5)
    pf = p1.then(fail)
    pf._wait()
    assert pf.is_rejected
    assert_exception(pf.reason, AssertionError, "Exception Message")

    p2 = Promise.reject(Exception("Error"))
    pr = p2.then(None, fail)
    pr._wait()
    assert pr.is_rejected
    assert_exception(pr.reason, AssertionError, "Exception Message")


def test_3_2_6_3_when_fulfilled():
    """
    Testing return of pending promises to make
    sure they are properly chained.
    This covers the case where the root promise
    is fulfilled after the chaining is defined.
    """

    p1 = Promise()
    pending = Promise()

    def p1_resolved(v):
        return pending

    pf = p1.then(p1_resolved)

    assert pending.is_pending
    assert pf.is_pending
    p1.do_resolve(10)
    pending.do_resolve(5)
    pending._wait()
    assert pending.is_fulfilled
    assert 5 == pending.get()
    pf._wait()
    assert pf.is_fulfilled
    assert 5 == pf.get()

    p2 = Promise()
    bad = Promise()
    pr = p2.then(lambda r: bad)
    assert bad.is_pending
    assert pr.is_pending
    p2.do_resolve(10)
    bad._reject_callback(Exception("Error"))
    bad._wait()
    assert bad.is_rejected
    assert_exception(bad.reason, Exception, "Error")
    pr._wait()
    assert pr.is_rejected
    assert_exception(pr.reason, Exception, "Error")


def test_3_2_6_3_if_fulfilled():
    """
    Testing return of pending promises to make
    sure they are properly chained.
    This covers the case where the root promise
    is fulfilled before the chaining is defined.
    """

    p1 = Promise()
    p1.do_resolve(10)
    pending = Promise()
    pending.do_resolve(5)
    pf = p1.then(lambda r: pending)
    pending._wait()
    assert pending.is_fulfilled
    assert 5 == pending.get()
    pf._wait()
    assert pf.is_fulfilled
    assert 5 == pf.get()

    p2 = Promise()
    p2.do_resolve(10)
    bad = Promise()
    bad.do_reject(Exception("Error"))
    pr = p2.then(lambda r: bad)
    bad._wait()
    assert_exception(bad.reason, Exception, "Error")
    pr._wait()
    assert pr.is_rejected
    assert_exception(pr.reason, Exception, "Error")


def test_3_2_6_3_when_rejected():
    """
    Testing return of pending promises to make
    sure they are properly chained.
    This covers the case where the root promise
    is rejected after the chaining is defined.
    """

    p1 = Promise()
    pending = Promise()
    pr = p1.then(None, lambda r: pending)
    assert pending.is_pending
    assert pr.is_pending
    p1.do_reject(Exception("Error"))
    pending.do_resolve(10)
    pending._wait()
    assert pending.is_fulfilled
    assert 10 == pending.get()
    assert 10 == pr.get()

    p2 = Promise()
    bad = Promise()
    pr = p2.then(None, lambda r: bad)
    assert bad.is_pending
    assert pr.is_pending
    p2.do_reject(Exception("Error"))
    bad.do_reject(Exception("Assertion"))
    bad._wait()
    assert bad.is_rejected
    assert_exception(bad.reason, Exception, "Assertion")
    pr._wait()
    assert pr.is_rejected
    assert_exception(pr.reason, Exception, "Assertion")


def test_3_2_6_3_if_rejected():
    """
    Testing return of pending promises to make
    sure they are properly chained.
    This covers the case where the root promise
    is rejected before the chaining is defined.
    """

    p1 = Promise()
    p1.do_reject(Exception("Error"))
    pending = Promise()
    pending.do_resolve(10)
    pr = p1.then(None, lambda r: pending)
    pending._wait()
    assert pending.is_fulfilled
    assert 10 == pending.get()
    pr._wait()
    assert pr.is_fulfilled
    assert 10 == pr.get()

    p2 = Promise()
    p2.do_reject(Exception("Error"))
    bad = Promise()
    bad.do_reject(Exception("Assertion"))
    pr = p2.then(None, lambda r: bad)
    bad._wait()
    assert bad.is_rejected
    assert_exception(bad.reason, Exception, "Assertion")
    pr._wait()
    assert pr.is_rejected
    assert_exception(pr.reason, Exception, "Assertion")


def test_3_2_6_4_pending():
    """
    Handles the case where the arguments to then
    are not functions or promises.
    """
    p1 = Promise()
    p2 = p1.then(5)
    p1.do_resolve(10)
    assert 10 == p1.get()
    p2._wait()
    assert p2.is_fulfilled
    assert 10 == p2.get()


def test_3_2_6_4_fulfilled():
    """
    Handles the case where the arguments to then
    are values, not functions or promises.
    """
    p1 = Promise()
    p1.do_resolve(10)
    p2 = p1.then(5)
    assert 10 == p1.get()
    p2._wait()
    assert p2.is_fulfilled
    assert 10 == p2.get()


def test_3_2_6_5_pending():
    """
    Handles the case where the arguments to then
    are values, not functions or promises.
    """
    p1 = Promise()
    p2 = p1.then(None, 5)
    p1.do_reject(Exception("Error"))
    assert_exception(p1.reason, Exception, "Error")
    p2._wait()
    assert p2.is_rejected
    assert_exception(p2.reason, Exception, "Error")


def test_3_2_6_5_rejected():
    """
    Handles the case where the arguments to then
    are values, not functions or promises.
    """
    p1 = Promise()
    p1.do_reject(Exception("Error"))
    p2 = p1.then(None, 5)
    assert_exception(p1.reason, Exception, "Error")
    p2._wait()
    assert p2.is_rejected
    assert_exception(p2.reason, Exception, "Error")


def test_chained_promises():
    """
    Handles the case where the arguments to then
    are values, not functions or promises.
    """
    p1 = Promise(lambda resolve, reject: resolve(Promise.resolve(True)))
    assert p1.get() == True


def test_promise_resolved_after():
    """
    The first argument to 'then' must be called when a promise is
    fulfilled.
    """

    c = Counter()

    def check(v, c):
        assert v == 5
        c.tick()

    p1 = Promise()
    p2 = p1.then(lambda v: check(v, c))
    p1.do_resolve(5)
    Promise.wait(p2)

    assert 1 == c.value()


def test_promise_follows_indifentely():
    a = Promise.resolve(None)
    b = a.then(lambda x: Promise.resolve("X"))
    e = Event()

    def b_then(v):

        c = Promise.resolve(None)
        d = c.then(lambda v: Promise.resolve("B"))
        return d

    promise = b.then(b_then)

    assert promise.get() == "B"


def test_promise_all_follows_indifentely():
    promises = Promise.all(
        [
            Promise.resolve("A"),
            Promise.resolve(None)
            .then(Promise.resolve)
            .then(lambda v: Promise.resolve(None).then(lambda v: Promise.resolve("B"))),
        ]
    )

    assert promises.get() == ["A", "B"]
