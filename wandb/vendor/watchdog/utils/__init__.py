#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2011 Yesudeep Mangalapilly <yesudeep@gmail.com>
# Copyright 2012 Google, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""
:module: watchdog.utils
:synopsis: Utility classes and functions.
:author: yesudeep@google.com (Yesudeep Mangalapilly)

Classes
-------
.. autoclass:: BaseThread
   :members:
   :show-inheritance:
   :inherited-members:

"""
import os
import sys
import threading
from watchdog.utils import platform
from watchdog.utils.compat import Event


if sys.version_info[0] == 2 and platform.is_windows():
    # st_ino is not implemented in os.stat on this platform
    import win32stat
    stat = win32stat.stat
else:
    stat = os.stat


def has_attribute(ob, attribute):
    """
    :func:`hasattr` swallows exceptions. :func:`has_attribute` tests a Python object for the
    presence of an attribute.

    :param ob:
        object to inspect
    :param attribute:
        ``str`` for the name of the attribute.
    """
    return getattr(ob, attribute, None) is not None


class UnsupportedLibc(Exception):
    pass


class BaseThread(threading.Thread):
    """ Convenience class for creating stoppable threads. """

    def __init__(self):
        threading.Thread.__init__(self)
        if has_attribute(self, 'daemon'):
            self.daemon = True
        else:
            self.setDaemon(True)
        self._stopped_event = Event()

        if not has_attribute(self._stopped_event, 'is_set'):
            self._stopped_event.is_set = self._stopped_event.isSet

    @property
    def stopped_event(self):
        return self._stopped_event

    def should_keep_running(self):
        """Determines whether the thread should continue running."""
        return not self._stopped_event.is_set()

    def on_thread_stop(self):
        """Override this method instead of :meth:`stop()`.
        :meth:`stop()` calls this method.

        This method is called immediately after the thread is signaled to stop.
        """
        pass

    def stop(self):
        """Signals the thread to stop."""
        self._stopped_event.set()
        self.on_thread_stop()

    def on_thread_start(self):
        """Override this method instead of :meth:`start()`. :meth:`start()`
        calls this method.

        This method is called right before this thread is started and this
        object’s run() method is invoked.
        """
        pass

    def start(self):
        self.on_thread_start()
        threading.Thread.start(self)


def load_module(module_name):
    """Imports a module given its name and returns a handle to it."""
    try:
        __import__(module_name)
    except ImportError:
        raise ImportError('No module named %s' % module_name)
    return sys.modules[module_name]


def load_class(dotted_path):
    """Loads and returns a class definition provided a dotted path
    specification the last part of the dotted path is the class name
    and there is at least one module name preceding the class name.

    Notes:
    You will need to ensure that the module you are trying to load
    exists in the Python path.

    Examples:
    - module.name.ClassName    # Provided module.name is in the Python path.
    - module.ClassName         # Provided module is in the Python path.

    What won't work:
    - ClassName
    - modle.name.ClassName     # Typo in module name.
    - module.name.ClasNam      # Typo in classname.
    """
    dotted_path_split = dotted_path.split('.')
    if len(dotted_path_split) > 1:
        klass_name = dotted_path_split[-1]
        module_name = '.'.join(dotted_path_split[:-1])

        module = load_module(module_name)
        if has_attribute(module, klass_name):
            klass = getattr(module, klass_name)
            return klass
            # Finally create and return an instance of the class
            # return klass(*args, **kwargs)
        else:
            raise AttributeError('Module %s does not have class attribute %s' % (
                                 module_name, klass_name))
    else:
        raise ValueError(
            'Dotted module path %s must contain a module name and a classname' % dotted_path)
