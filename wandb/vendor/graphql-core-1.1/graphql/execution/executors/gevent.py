from __future__ import absolute_import

import gevent
from promise import Promise

from .utils import process


class GeventExecutor(object):

    def __init__(self):
        self.jobs = []

    def wait_until_finished(self):
        [j.join() for j in self.jobs]
        # gevent.joinall(self.jobs)

    def execute(self, fn, *args, **kwargs):
        promise = Promise()
        job = gevent.spawn(process, promise, fn, args, kwargs)
        self.jobs.append(job)
        return promise
