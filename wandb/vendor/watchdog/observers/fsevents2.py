# -*- coding: utf-8 -*-
#
# Copyright 2014 Thomas Amland <thomas.amland@gmail.com>
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
:module: watchdog.observers.fsevents2
:synopsis: FSEvents based emitter implementation.
:platforms: Mac OS X
"""

import os
import logging
import unicodedata
from threading import Thread
from watchdog.utils.compat import queue

from watchdog.events import (
    FileDeletedEvent,
    FileModifiedEvent,
    FileCreatedEvent,
    FileMovedEvent,
    DirDeletedEvent,
    DirModifiedEvent,
    DirCreatedEvent,
    DirMovedEvent
)
from watchdog.observers.api import (
    BaseObserver,
    EventEmitter,
    DEFAULT_EMITTER_TIMEOUT,
    DEFAULT_OBSERVER_TIMEOUT,
)

# pyobjc
import AppKit
from FSEvents import (
    FSEventStreamCreate,
    CFRunLoopGetCurrent,
    FSEventStreamScheduleWithRunLoop,
    FSEventStreamStart,
    CFRunLoopRun,
    CFRunLoopStop,
    FSEventStreamStop,
    FSEventStreamInvalidate,
    FSEventStreamRelease,
)

from FSEvents import (
    kCFAllocatorDefault,
    kCFRunLoopDefaultMode,
    kFSEventStreamEventIdSinceNow,
    kFSEventStreamCreateFlagNoDefer,
    kFSEventStreamCreateFlagFileEvents,
    kFSEventStreamEventFlagItemCreated,
    kFSEventStreamEventFlagItemRemoved,
    kFSEventStreamEventFlagItemInodeMetaMod,
    kFSEventStreamEventFlagItemRenamed,
    kFSEventStreamEventFlagItemModified,
    kFSEventStreamEventFlagItemFinderInfoMod,
    kFSEventStreamEventFlagItemChangeOwner,
    kFSEventStreamEventFlagItemXattrMod,
    kFSEventStreamEventFlagItemIsDir,
    kFSEventStreamEventFlagItemIsSymlink,
)

logger = logging.getLogger(__name__)


class FSEventsQueue(Thread):
    """ Low level FSEvents client. """

    def __init__(self, path):
        Thread.__init__(self)
        self._queue = queue.Queue()
        self._run_loop = None

        if isinstance(path, bytes):
            path = path.decode('utf-8')
        self._path = unicodedata.normalize('NFC', path)

        context = None
        latency = 1.0
        self._stream_ref = FSEventStreamCreate(
            kCFAllocatorDefault, self._callback, context, [self._path],
            kFSEventStreamEventIdSinceNow, latency,
            kFSEventStreamCreateFlagNoDefer | kFSEventStreamCreateFlagFileEvents)
        if self._stream_ref is None:
            raise IOError("FSEvents. Could not create stream.")

    def run(self):
        pool = AppKit.NSAutoreleasePool.alloc().init()
        self._run_loop = CFRunLoopGetCurrent()
        FSEventStreamScheduleWithRunLoop(
            self._stream_ref, self._run_loop, kCFRunLoopDefaultMode)
        if not FSEventStreamStart(self._stream_ref):
            FSEventStreamInvalidate(self._stream_ref)
            FSEventStreamRelease(self._stream_ref)
            raise IOError("FSEvents. Could not start stream.")

        CFRunLoopRun()
        FSEventStreamStop(self._stream_ref)
        FSEventStreamInvalidate(self._stream_ref)
        FSEventStreamRelease(self._stream_ref)
        del pool
        # Make sure waiting thread is notified
        self._queue.put(None)

    def stop(self):
        if self._run_loop is not None:
            CFRunLoopStop(self._run_loop)

    def _callback(self, streamRef, clientCallBackInfo, numEvents, eventPaths, eventFlags, eventIDs):
        events = [NativeEvent(path, flags, _id) for path, flags, _id in
                  zip(eventPaths, eventFlags, eventIDs)]
        logger.debug("FSEvents callback. Got %d events:" % numEvents)
        for e in events:
            logger.debug(e)
        self._queue.put(events)

    def read_events(self):
        """
        Returns a list or one or more events, or None if there are no more
        events to be read.
        """
        if not self.is_alive():
            return None
        return self._queue.get()


class NativeEvent(object):
    def __init__(self, path, flags, event_id):
        self.path = path
        self.flags = flags
        self.event_id = event_id
        self.is_created = bool(flags & kFSEventStreamEventFlagItemCreated)
        self.is_removed = bool(flags & kFSEventStreamEventFlagItemRemoved)
        self.is_renamed = bool(flags & kFSEventStreamEventFlagItemRenamed)
        self.is_modified = bool(flags & kFSEventStreamEventFlagItemModified)
        self.is_change_owner = bool(flags & kFSEventStreamEventFlagItemChangeOwner)
        self.is_inode_meta_mod = bool(flags & kFSEventStreamEventFlagItemInodeMetaMod)
        self.is_finder_info_mod = bool(flags & kFSEventStreamEventFlagItemFinderInfoMod)
        self.is_xattr_mod = bool(flags & kFSEventStreamEventFlagItemXattrMod)
        self.is_symlink = bool(flags & kFSEventStreamEventFlagItemIsSymlink)
        self.is_directory = bool(flags & kFSEventStreamEventFlagItemIsDir)

    @property
    def _event_type(self):
        if self.is_created: return "Created"
        if self.is_removed: return "Removed"
        if self.is_renamed: return "Renamed"
        if self.is_modified: return "Modified"
        if self.is_inode_meta_mod: return "InodeMetaMod"
        if self.is_xattr_mod: return "XattrMod"
        return "Unknown"

    def __repr__(self):
        s ="<NativeEvent: path=%s, type=%s, is_dir=%s, flags=%s, id=%s>"
        return s % (repr(self.path), self._event_type, self.is_directory, hex(self.flags), self.event_id)


class FSEventsEmitter(EventEmitter):
    """
    FSEvents based event emitter. Handles conversion of native events.
    """

    def __init__(self, event_queue, watch, timeout=DEFAULT_EMITTER_TIMEOUT):
        EventEmitter.__init__(self, event_queue, watch, timeout)
        self._fsevents = FSEventsQueue(watch.path)
        self._fsevents.start()

    def on_thread_stop(self):
        self._fsevents.stop()

    def queue_events(self, timeout):
        events = self._fsevents.read_events()
        if events is None:
            return
        i = 0
        while i < len(events):
            event = events[i]

            # For some reason the create and remove flags are sometimes also
            # set for rename and modify type events, so let those take
            # precedence.
            if event.is_renamed:
                # Internal moves appears to always be consecutive in the same
                # buffer and have IDs differ by exactly one (while others
                # don't) making it possible to pair up the two events coming
                # from a singe move operation. (None of this is documented!)
                # Otherwise, guess whether file was moved in or out.
                #TODO: handle id wrapping
                if (i+1 < len(events) and events[i+1].is_renamed and
                        events[i+1].event_id == event.event_id + 1):
                    cls = DirMovedEvent if event.is_directory else FileMovedEvent
                    self.queue_event(cls(event.path, events[i+1].path))
                    self.queue_event(DirModifiedEvent(os.path.dirname(event.path)))
                    self.queue_event(DirModifiedEvent(os.path.dirname(events[i+1].path)))
                    i += 1
                elif os.path.exists(event.path):
                    cls = DirCreatedEvent if event.is_directory else FileCreatedEvent
                    self.queue_event(cls(event.path))
                    self.queue_event(DirModifiedEvent(os.path.dirname(event.path)))
                else:
                    cls = DirDeletedEvent if event.is_directory else FileDeletedEvent
                    self.queue_event(cls(event.path))
                    self.queue_event(DirModifiedEvent(os.path.dirname(event.path)))
                #TODO: generate events for tree

            elif event.is_modified or event.is_inode_meta_mod or event.is_xattr_mod :
                cls = DirModifiedEvent if event.is_directory else FileModifiedEvent
                self.queue_event(cls(event.path))

            elif event.is_created:
                cls = DirCreatedEvent if event.is_directory else FileCreatedEvent
                self.queue_event(cls(event.path))
                self.queue_event(DirModifiedEvent(os.path.dirname(event.path)))

            elif event.is_removed:
                cls = DirDeletedEvent if event.is_directory else FileDeletedEvent
                self.queue_event(cls(event.path))
                self.queue_event(DirModifiedEvent(os.path.dirname(event.path)))
            i += 1


class FSEventsObserver2(BaseObserver):
    def __init__(self, timeout=DEFAULT_OBSERVER_TIMEOUT):
        BaseObserver.__init__(self, emitter_class=FSEventsEmitter, timeout=timeout)
