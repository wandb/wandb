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
:module: watchdog.observers
:synopsis: Observer that picks a native implementation if available.
:author: yesudeep@google.com (Yesudeep Mangalapilly)


Classes
=======
.. autoclass:: Observer
   :members:
   :show-inheritance:
   :inherited-members:
   
Observer thread that schedules watching directories and dispatches
calls to event handlers.

You can also import platform specific classes directly and use it instead
of :class:`Observer`.  Here is a list of implemented observer classes.:

============== ================================ ==============================
Class          Platforms                        Note
============== ================================ ==============================
|Inotify|      Linux 2.6.13+                    ``inotify(7)`` based observer
|FSEvents|     Mac OS X                         FSEvents based observer
|Kqueue|       Mac OS X and BSD with kqueue(2)  ``kqueue(2)`` based observer
|WinApi|       MS Windows                       Windows API-based observer
|Polling|      Any                              fallback implementation
============== ================================ ==============================

.. |Inotify|     replace:: :class:`.inotify.InotifyObserver`
.. |FSEvents|    replace:: :class:`.fsevents.FSEventsObserver`
.. |Kqueue|      replace:: :class:`.kqueue.KqueueObserver`
.. |WinApi|      replace:: :class:`.read_directory_changes.WindowsApiObserver`
.. |WinApiAsync| replace:: :class:`.read_directory_changes_async.WindowsApiAsyncObserver`
.. |Polling|     replace:: :class:`.polling.PollingObserver`

"""

import warnings
from watchdog.utils import platform
from watchdog.utils import UnsupportedLibc

if platform.is_linux():
    try:
        from .inotify import InotifyObserver as Observer
    except UnsupportedLibc:
        from .polling import PollingObserver as Observer

elif platform.is_darwin():
    # FIXME: catching too broad. Error prone
    try:
        from .fsevents import FSEventsObserver as Observer
    except:
        try:
            from .kqueue import KqueueObserver as Observer
            warnings.warn("Failed to import fsevents. Fall back to kqueue")
        except:
            from .polling import PollingObserver as Observer
            warnings.warn("Failed to import fsevents and kqueue. Fall back to polling.")

elif platform.is_bsd():
    from .kqueue import KqueueObserver as Observer

elif platform.is_windows():
    # TODO: find a reliable way of checking Windows version and import
    # polling explicitly for Windows XP
    try:
        from .read_directory_changes import WindowsApiObserver as Observer
    except:
        from .polling import PollingObserver as Observer
        warnings.warn("Failed to import read_directory_changes. Fall back to polling.")

else:
    from .polling import PollingObserver as Observer

__all__ = ["Observer"]
