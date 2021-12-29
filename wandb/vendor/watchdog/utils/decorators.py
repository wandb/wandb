#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Most of this code was obtained from the Python documentation online.

"""Decorator utility functions.

decorators:
- synchronized
- propertyx
- accepts
- returns
- singleton
- attrs
- deprecated
"""

import functools
import warnings
import threading
import sys


def synchronized(lock=None):
    """Decorator that synchronizes a method or a function with a mutex lock.

    Example usage:

        @synchronized()
        def operation(self, a, b):
            ...
    """
    if lock is None:
        lock = threading.Lock()

    def wrapper(function):
        def new_function(*args, **kwargs):
            lock.acquire()
            try:
                return function(*args, **kwargs)
            finally:
                lock.release()

        return new_function

    return wrapper


def propertyx(function):
    """Decorator to easily create properties in classes.

    Example:

        class Angle(object):
            def __init__(self, rad):
                self._rad = rad

            @property
            def rad():
                def fget(self):
                    return self._rad
                def fset(self, angle):
                    if isinstance(angle, Angle):
                        angle = angle.rad
                    self._rad = float(angle)

    Arguments:
    - `function`: The function to be decorated.
    """
    keys = ('fget', 'fset', 'fdel')
    func_locals = {'doc': function.__doc__}

    def probe_func(frame, event, arg):
        if event == 'return':
            locals = frame.f_locals
            func_locals.update(dict((k, locals.get(k)) for k in keys))
            sys.settrace(None)
        return probe_func

    sys.settrace(probe_func)
    function()
    return property(**func_locals)


def accepts(*types):
    """Decorator to ensure that the decorated function accepts the given types as arguments.

    Example:
        @accepts(int, (int,float))
        @returns((int,float))
        def func(arg1, arg2):
            return arg1 * arg2
    """

    def check_accepts(f):
        assert len(types) == f.__code__.co_argcount

        def new_f(*args, **kwds):
            for (a, t) in zip(args, types):
                assert isinstance(a, t),\
                    "arg %r does not match %s" % (a, t)
            return f(*args, **kwds)

        new_f.__name__ = f.__name__
        return new_f

    return check_accepts


def returns(rtype):
    """Decorator to ensure that the decorated function returns the given
    type as argument.

    Example:
        @accepts(int, (int,float))
        @returns((int,float))
        def func(arg1, arg2):
            return arg1 * arg2
    """

    def check_returns(f):
        def new_f(*args, **kwds):
            result = f(*args, **kwds)
            assert isinstance(result, rtype),\
                "return value %r does not match %s" % (result, rtype)
            return result

        new_f.__name__ = f.__name__
        return new_f

    return check_returns


def singleton(cls):
    """Decorator to ensures a class follows the singleton pattern.

    Example:
        @singleton
        class MyClass:
            ...
    """
    instances = {}

    def getinstance():
        if cls not in instances:
            instances[cls] = cls()
        return instances[cls]

    return getinstance


def attrs(**kwds):
    """Decorator to add attributes to a function.

    Example:

        @attrs(versionadded="2.2",
               author="Guido van Rossum")
        def mymethod(f):
            ...
    """

    def decorate(f):
        for k in kwds:
            setattr(f, k, kwds[k])
        return f

    return decorate


def deprecated(func):
    """This is a decorator which can be used to mark functions
    as deprecated. It will result in a warning being emitted
    when the function is used.

    ## Usage examples ##
    @deprecated
    def my_func():
        pass

    @other_decorators_must_be_upper
    @deprecated
    def my_func():
        pass
    """

    @functools.wraps(func)
    def new_func(*args, **kwargs):
        warnings.warn_explicit(
            "Call to deprecated function %(funcname)s." % {
            'funcname': func.__name__,
            },
            category=DeprecationWarning,
            filename=func.__code__.co_filename,
            lineno=func.__code__.co_firstlineno + 1
        )
        return func(*args, **kwargs)

    return new_func
