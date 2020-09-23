from __future__ import absolute_import

from asyncio import Future, get_event_loop, iscoroutine, wait

from promise import Promise

try:
    from asyncio import ensure_future
except ImportError:
    # ensure_future is only implemented in Python 3.4.4+
    def ensure_future(coro_or_future, loop=None):
        """Wrap a coroutine or an awaitable in a future.

        If the argument is a Future, it is returned directly.
        """
        if isinstance(coro_or_future, Future):
            if loop is not None and loop is not coro_or_future._loop:
                raise ValueError('loop argument must agree with Future')
            return coro_or_future
        elif iscoroutine(coro_or_future):
            if loop is None:
                loop = get_event_loop()
            task = loop.create_task(coro_or_future)
            if task._source_traceback:
                del task._source_traceback[-1]
            return task
        else:
            raise TypeError('A Future, a coroutine or an awaitable is required')


class AsyncioExecutor(object):

    def __init__(self, loop=None):
        if loop is None:
            loop = get_event_loop()
        self.loop = loop
        self.futures = []

    def wait_until_finished(self):
        # if there are futures to wait for
        while self.futures:
            # wait for the futures to finish
            futures = self.futures
            self.futures = []
            self.loop.run_until_complete(wait(futures))

    def execute(self, fn, *args, **kwargs):
        result = fn(*args, **kwargs)
        if isinstance(result, Future) or iscoroutine(result):
            future = ensure_future(result, loop=self.loop)
            self.futures.append(future)
            return Promise.resolve(future)
        return result
