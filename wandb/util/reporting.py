"""
reporting.
"""

import logging

logger = logging.getLogger("wandb")

class _Reporter(object):
    def __init__(self, settings):
        self._settings = settings
        self._errors = []
        self._warnings = []
        self._d = dict()

    def error(self, __s, *args):
        pass

    def warning(self, __s, *args):
        pass

    def info(self, __s, *args):
        print(("[INFO]" + __s) % args)

    def internal(self, __s, *args):
        pass

    def problem(self, bool, __s=None, *args):
        pass

    def set_context(self, __d=None, **kwargs):
        if __d:
            self._d.update(__d)
        self._d.update(**kwargs)

    def clear_context(self, keys=None):
        if keys is None:
            self._d = dict()
            return
        for k in keys:
            self._d.pop(k, None)


class Reporter(object):
    _instance = None

    def __init__(self, settings=None):
        if Reporter._instance is not None:
            return
        if settings is None:
            logging.error("internal issue: reporter not setup")

        Reporter._instance = _Reporter(settings)

    def __getattr__(self, name):
        return getattr(self._instance, name)


def setup_reporter(settings):
    if not settings.frozen:
        logging.error("internal issue: settings not frozen")
    r = Reporter(settings=settings)
    return r


def get_reporter():
    r = Reporter()
    return r
