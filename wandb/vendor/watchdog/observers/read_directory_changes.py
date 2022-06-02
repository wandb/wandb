#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2011 Yesudeep Mangalapilly <yesudeep@gmail.com>
# Copyright 2012 Google, Inc.
# Copyright 2014 Thomas Amland
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

from __future__ import with_statement

import threading
import os.path
import time

from watchdog.events import (
    DirCreatedEvent,
    DirMovedEvent,
    DirModifiedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileMovedEvent,
    FileModifiedEvent,
    generate_sub_moved_events,
    generate_sub_created_events,
)

from watchdog.observers.api import (
    EventEmitter,
    BaseObserver,
    DEFAULT_OBSERVER_TIMEOUT,
    DEFAULT_EMITTER_TIMEOUT
)

from watchdog.observers.winapi import (
    read_events,
    get_directory_handle,
    close_directory_handle,
)


# HACK:
WATCHDOG_TRAVERSE_MOVED_DIR_DELAY = 1   # seconds


class WindowsApiEmitter(EventEmitter):
    """
    Windows API-based emitter that uses ReadDirectoryChangesW
    to detect file system changes for a watch.
    """

    def __init__(self, event_queue, watch, timeout=DEFAULT_EMITTER_TIMEOUT):
        EventEmitter.__init__(self, event_queue, watch, timeout)
        self._lock = threading.Lock()
        self._handle = None

    def on_thread_start(self):
        self._handle = get_directory_handle(self.watch.path)

    def on_thread_stop(self):
        if self._handle:
            close_directory_handle(self._handle)

    def queue_events(self, timeout):
        winapi_events = read_events(self._handle, self.watch.is_recursive)
        with self._lock:
            last_renamed_src_path = ""
            for winapi_event in winapi_events:
                src_path = os.path.join(self.watch.path, winapi_event.src_path)
                
                if winapi_event.is_renamed_old:
                    last_renamed_src_path = src_path
                elif winapi_event.is_renamed_new:
                    dest_path = src_path
                    src_path = last_renamed_src_path
                    if os.path.isdir(dest_path):
                        event = DirMovedEvent(src_path, dest_path)
                        if self.watch.is_recursive:
                            # HACK: We introduce a forced delay before
                            # traversing the moved directory. This will read
                            # only file movement that finishes within this
                            # delay time.
                            time.sleep(WATCHDOG_TRAVERSE_MOVED_DIR_DELAY)
                            # The following block of code may not
                            # obtain moved events for the entire tree if
                            # the I/O is not completed within the above
                            # delay time. So, it's not guaranteed to work.
                            # TODO: Come up with a better solution, possibly
                            # a way to wait for I/O to complete before
                            # queuing events.
                            for sub_moved_event in generate_sub_moved_events(src_path, dest_path):
                                self.queue_event(sub_moved_event)
                        self.queue_event(event)
                    else:
                        self.queue_event(FileMovedEvent(src_path, dest_path))
                elif winapi_event.is_modified:
                    cls = DirModifiedEvent if os.path.isdir(src_path) else FileModifiedEvent
                    self.queue_event(cls(src_path))
                elif winapi_event.is_added:
                    isdir = os.path.isdir(src_path)
                    cls = DirCreatedEvent if isdir else FileCreatedEvent
                    self.queue_event(cls(src_path))
                    if isdir:
                        # If a directory is moved from outside the watched folder to inside it
                        # we only get a created directory event out of it, not any events for its children
                        # so use the same hack as for file moves to get the child events
                        time.sleep(WATCHDOG_TRAVERSE_MOVED_DIR_DELAY)
                        sub_events = generate_sub_created_events(src_path)
                        for sub_created_event in sub_events:
                            self.queue_event(sub_created_event)
                elif winapi_event.is_removed:
                    self.queue_event(FileDeletedEvent(src_path))


class WindowsApiObserver(BaseObserver):
    """
    Observer thread that schedules watching directories and dispatches
    calls to event handlers.
    """

    def __init__(self, timeout=DEFAULT_OBSERVER_TIMEOUT):
        BaseObserver.__init__(self, emitter_class=WindowsApiEmitter,
                              timeout=timeout)
