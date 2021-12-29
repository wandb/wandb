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
:module: watchdog.events
:synopsis: File system events and event handlers.
:author: yesudeep@google.com (Yesudeep Mangalapilly)

Event Classes
-------------
.. autoclass:: FileSystemEvent
   :members:
   :show-inheritance:
   :inherited-members:

.. autoclass:: FileSystemMovedEvent
   :members:
   :show-inheritance:

.. autoclass:: FileMovedEvent
   :members:
   :show-inheritance:

.. autoclass:: DirMovedEvent
   :members:
   :show-inheritance:

.. autoclass:: FileModifiedEvent
   :members:
   :show-inheritance:

.. autoclass:: DirModifiedEvent
   :members:
   :show-inheritance:

.. autoclass:: FileCreatedEvent
   :members:
   :show-inheritance:

.. autoclass:: DirCreatedEvent
   :members:
   :show-inheritance:

.. autoclass:: FileDeletedEvent
   :members:
   :show-inheritance:

.. autoclass:: DirDeletedEvent
   :members:
   :show-inheritance:


Event Handler Classes
---------------------
.. autoclass:: FileSystemEventHandler
   :members:
   :show-inheritance:

.. autoclass:: PatternMatchingEventHandler
   :members:
   :show-inheritance:

.. autoclass:: RegexMatchingEventHandler
   :members:
   :show-inheritance:

.. autoclass:: LoggingEventHandler
   :members:
   :show-inheritance:

"""

import os.path
import logging
import re
from pathtools.patterns import match_any_paths
from watchdog.utils import has_attribute
from watchdog.utils import unicode_paths


EVENT_TYPE_MOVED = 'moved'
EVENT_TYPE_DELETED = 'deleted'
EVENT_TYPE_CREATED = 'created'
EVENT_TYPE_MODIFIED = 'modified'


class FileSystemEvent(object):
    """
    Immutable type that represents a file system event that is triggered
    when a change occurs on the monitored file system.

    All FileSystemEvent objects are required to be immutable and hence
    can be used as keys in dictionaries or be added to sets.
    """

    event_type = None
    """The type of the event as a string."""

    is_directory = False
    """True if event was emitted for a directory; False otherwise."""

    def __init__(self, src_path):
        self._src_path = src_path

    @property
    def src_path(self):
        """Source path of the file system object that triggered this event."""
        return self._src_path

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return ("<%(class_name)s: event_type=%(event_type)s, "
                "src_path=%(src_path)r, "
                "is_directory=%(is_directory)s>"
                ) % (dict(
                     class_name=self.__class__.__name__,
                     event_type=self.event_type,
                     src_path=self.src_path,
                     is_directory=self.is_directory))

    # Used for comparison of events.
    @property
    def key(self):
        return (self.event_type, self.src_path, self.is_directory)

    def __eq__(self, event):
        return self.key == event.key

    def __ne__(self, event):
        return self.key != event.key

    def __hash__(self):
        return hash(self.key)


class FileSystemMovedEvent(FileSystemEvent):
    """
    File system event representing any kind of file system movement.
    """

    event_type = EVENT_TYPE_MOVED

    def __init__(self, src_path, dest_path):
        super(FileSystemMovedEvent, self).__init__(src_path)
        self._dest_path = dest_path

    @property
    def dest_path(self):
        """The destination path of the move event."""
        return self._dest_path

    # Used for hashing this as an immutable object.
    @property
    def key(self):
        return (self.event_type, self.src_path, self.dest_path, self.is_directory)

    def __repr__(self):
        return ("<%(class_name)s: src_path=%(src_path)r, "
                "dest_path=%(dest_path)r, "
                "is_directory=%(is_directory)s>"
                ) % (dict(class_name=self.__class__.__name__,
                          src_path=self.src_path,
                          dest_path=self.dest_path,
                          is_directory=self.is_directory))


# File events.


class FileDeletedEvent(FileSystemEvent):
    """File system event representing file deletion on the file system."""

    event_type = EVENT_TYPE_DELETED

    def __init__(self, src_path):
        super(FileDeletedEvent, self).__init__(src_path)

    def __repr__(self):
        return "<%(class_name)s: src_path=%(src_path)r>" %\
               dict(class_name=self.__class__.__name__,
                    src_path=self.src_path)


class FileModifiedEvent(FileSystemEvent):
    """File system event representing file modification on the file system."""

    event_type = EVENT_TYPE_MODIFIED

    def __init__(self, src_path):
        super(FileModifiedEvent, self).__init__(src_path)

    def __repr__(self):
        return ("<%(class_name)s: src_path=%(src_path)r>"
                ) % (dict(class_name=self.__class__.__name__,
                          src_path=self.src_path))


class FileCreatedEvent(FileSystemEvent):
    """File system event representing file creation on the file system."""

    event_type = EVENT_TYPE_CREATED

    def __init__(self, src_path):
        super(FileCreatedEvent, self).__init__(src_path)

    def __repr__(self):
        return ("<%(class_name)s: src_path=%(src_path)r>"
                ) % (dict(class_name=self.__class__.__name__,
                          src_path=self.src_path))


class FileMovedEvent(FileSystemMovedEvent):
    """File system event representing file movement on the file system."""

    def __init__(self, src_path, dest_path):
        super(FileMovedEvent, self).__init__(src_path, dest_path)

    def __repr__(self):
        return ("<%(class_name)s: src_path=%(src_path)r, "
                "dest_path=%(dest_path)r>"
                ) % (dict(class_name=self.__class__.__name__,
                          src_path=self.src_path,
                          dest_path=self.dest_path))


# Directory events.


class DirDeletedEvent(FileSystemEvent):
    """File system event representing directory deletion on the file system."""

    event_type = EVENT_TYPE_DELETED
    is_directory = True

    def __init__(self, src_path):
        super(DirDeletedEvent, self).__init__(src_path)

    def __repr__(self):
        return ("<%(class_name)s: src_path=%(src_path)r>"
                ) % (dict(class_name=self.__class__.__name__,
                          src_path=self.src_path))


class DirModifiedEvent(FileSystemEvent):
    """
    File system event representing directory modification on the file system.
    """

    event_type = EVENT_TYPE_MODIFIED
    is_directory = True

    def __init__(self, src_path):
        super(DirModifiedEvent, self).__init__(src_path)

    def __repr__(self):
        return ("<%(class_name)s: src_path=%(src_path)r>"
                ) % (dict(class_name=self.__class__.__name__,
                          src_path=self.src_path))


class DirCreatedEvent(FileSystemEvent):
    """File system event representing directory creation on the file system."""

    event_type = EVENT_TYPE_CREATED
    is_directory = True

    def __init__(self, src_path):
        super(DirCreatedEvent, self).__init__(src_path)

    def __repr__(self):
        return ("<%(class_name)s: src_path=%(src_path)r>"
                ) % (dict(class_name=self.__class__.__name__,
                          src_path=self.src_path))


class DirMovedEvent(FileSystemMovedEvent):
    """File system event representing directory movement on the file system."""

    is_directory = True

    def __init__(self, src_path, dest_path):
        super(DirMovedEvent, self).__init__(src_path, dest_path)

    def __repr__(self):
        return ("<%(class_name)s: src_path=%(src_path)r, "
                "dest_path=%(dest_path)r>"
                ) % (dict(class_name=self.__class__.__name__,
                          src_path=self.src_path,
                          dest_path=self.dest_path))


class FileSystemEventHandler(object):
    """
    Base file system event handler that you can override methods from.
    """

    def dispatch(self, event):
        """Dispatches events to the appropriate methods.

        :param event:
            The event object representing the file system event.
        :type event:
            :class:`FileSystemEvent`
        """
        self.on_any_event(event)
        _method_map = {
            EVENT_TYPE_MODIFIED: self.on_modified,
            EVENT_TYPE_MOVED: self.on_moved,
            EVENT_TYPE_CREATED: self.on_created,
            EVENT_TYPE_DELETED: self.on_deleted,
        }
        event_type = event.event_type
        _method_map[event_type](event)

    def on_any_event(self, event):
        """Catch-all event handler.

        :param event:
            The event object representing the file system event.
        :type event:
            :class:`FileSystemEvent`
        """

    def on_moved(self, event):
        """Called when a file or a directory is moved or renamed.

        :param event:
            Event representing file/directory movement.
        :type event:
            :class:`DirMovedEvent` or :class:`FileMovedEvent`
        """

    def on_created(self, event):
        """Called when a file or directory is created.

        :param event:
            Event representing file/directory creation.
        :type event:
            :class:`DirCreatedEvent` or :class:`FileCreatedEvent`
        """

    def on_deleted(self, event):
        """Called when a file or directory is deleted.

        :param event:
            Event representing file/directory deletion.
        :type event:
            :class:`DirDeletedEvent` or :class:`FileDeletedEvent`
        """

    def on_modified(self, event):
        """Called when a file or directory is modified.

        :param event:
            Event representing file/directory modification.
        :type event:
            :class:`DirModifiedEvent` or :class:`FileModifiedEvent`
        """


class PatternMatchingEventHandler(FileSystemEventHandler):
    """
    Matches given patterns with file paths associated with occurring events.
    """

    def __init__(self, patterns=None, ignore_patterns=None,
                 ignore_directories=False, case_sensitive=False):
        super(PatternMatchingEventHandler, self).__init__()

        self._patterns = patterns
        self._ignore_patterns = ignore_patterns
        self._ignore_directories = ignore_directories
        self._case_sensitive = case_sensitive

    @property
    def patterns(self):
        """
        (Read-only)
        Patterns to allow matching event paths.
        """
        return self._patterns

    @property
    def ignore_patterns(self):
        """
        (Read-only)
        Patterns to ignore matching event paths.
        """
        return self._ignore_patterns

    @property
    def ignore_directories(self):
        """
        (Read-only)
        ``True`` if directories should be ignored; ``False`` otherwise.
        """
        return self._ignore_directories

    @property
    def case_sensitive(self):
        """
        (Read-only)
        ``True`` if path names should be matched sensitive to case; ``False``
        otherwise.
        """
        return self._case_sensitive

    def dispatch(self, event):
        """Dispatches events to the appropriate methods.

        :param event:
            The event object representing the file system event.
        :type event:
            :class:`FileSystemEvent`
        """
        if self.ignore_directories and event.is_directory:
            return

        paths = []
        if has_attribute(event, 'dest_path'):
            paths.append(unicode_paths.decode(event.dest_path))
        if event.src_path:
            paths.append(unicode_paths.decode(event.src_path))

        if match_any_paths(paths,
                           included_patterns=self.patterns,
                           excluded_patterns=self.ignore_patterns,
                           case_sensitive=self.case_sensitive):
            self.on_any_event(event)
            _method_map = {
                EVENT_TYPE_MODIFIED: self.on_modified,
                EVENT_TYPE_MOVED: self.on_moved,
                EVENT_TYPE_CREATED: self.on_created,
                EVENT_TYPE_DELETED: self.on_deleted,
            }
            event_type = event.event_type
            _method_map[event_type](event)


class RegexMatchingEventHandler(FileSystemEventHandler):
    """
    Matches given regexes with file paths associated with occurring events.
    """

    def __init__(self, regexes=[r".*"], ignore_regexes=[],
                 ignore_directories=False, case_sensitive=False):
        super(RegexMatchingEventHandler, self).__init__()

        if case_sensitive:
            self._regexes = [re.compile(r) for r in regexes]
            self._ignore_regexes = [re.compile(r) for r in ignore_regexes]
        else:
            self._regexes = [re.compile(r, re.I) for r in regexes]
            self._ignore_regexes = [re.compile(r, re.I) for r in ignore_regexes]
        self._ignore_directories = ignore_directories
        self._case_sensitive = case_sensitive

    @property
    def regexes(self):
        """
        (Read-only)
        Regexes to allow matching event paths.
        """
        return self._regexes

    @property
    def ignore_regexes(self):
        """
        (Read-only)
        Regexes to ignore matching event paths.
        """
        return self._ignore_regexes

    @property
    def ignore_directories(self):
        """
        (Read-only)
        ``True`` if directories should be ignored; ``False`` otherwise.
        """
        return self._ignore_directories

    @property
    def case_sensitive(self):
        """
        (Read-only)
        ``True`` if path names should be matched sensitive to case; ``False``
        otherwise.
        """
        return self._case_sensitive

    def dispatch(self, event):
        """Dispatches events to the appropriate methods.

        :param event:
            The event object representing the file system event.
        :type event:
            :class:`FileSystemEvent`
        """
        if self.ignore_directories and event.is_directory:
            return

        paths = []
        if has_attribute(event, 'dest_path'):
            paths.append(unicode_paths.decode(event.dest_path))
        if event.src_path:
            paths.append(unicode_paths.decode(event.src_path))

        if any(r.match(p) for r in self.ignore_regexes for p in paths):
            return

        if any(r.match(p) for r in self.regexes for p in paths):
            self.on_any_event(event)
            _method_map = {
                EVENT_TYPE_MODIFIED: self.on_modified,
                EVENT_TYPE_MOVED: self.on_moved,
                EVENT_TYPE_CREATED: self.on_created,
                EVENT_TYPE_DELETED: self.on_deleted,
            }
            event_type = event.event_type
            _method_map[event_type](event)


class LoggingEventHandler(FileSystemEventHandler):
    """Logs all the events captured."""

    def on_moved(self, event):
        super(LoggingEventHandler, self).on_moved(event)

        what = 'directory' if event.is_directory else 'file'
        logging.info("Moved %s: from %s to %s", what, event.src_path,
                     event.dest_path)

    def on_created(self, event):
        super(LoggingEventHandler, self).on_created(event)

        what = 'directory' if event.is_directory else 'file'
        logging.info("Created %s: %s", what, event.src_path)

    def on_deleted(self, event):
        super(LoggingEventHandler, self).on_deleted(event)

        what = 'directory' if event.is_directory else 'file'
        logging.info("Deleted %s: %s", what, event.src_path)

    def on_modified(self, event):
        super(LoggingEventHandler, self).on_modified(event)

        what = 'directory' if event.is_directory else 'file'
        logging.info("Modified %s: %s", what, event.src_path)


class LoggingFileSystemEventHandler(LoggingEventHandler):
    """
    For backwards-compatibility. Please use :class:`LoggingEventHandler`
    instead.
    """


def generate_sub_moved_events(src_dir_path, dest_dir_path):
    """Generates an event list of :class:`DirMovedEvent` and
    :class:`FileMovedEvent` objects for all the files and directories within
    the given moved directory that were moved along with the directory.

    :param src_dir_path:
        The source path of the moved directory.
    :param dest_dir_path:
        The destination path of the moved directory.
    :returns:
        An iterable of file system events of type :class:`DirMovedEvent` and
        :class:`FileMovedEvent`.
    """
    for root, directories, filenames in os.walk(dest_dir_path):
        for directory in directories:
            full_path = os.path.join(root, directory)
            renamed_path = full_path.replace(dest_dir_path, src_dir_path) if src_dir_path else None
            yield DirMovedEvent(renamed_path, full_path)
        for filename in filenames:
            full_path = os.path.join(root, filename)
            renamed_path = full_path.replace(dest_dir_path, src_dir_path) if src_dir_path else None
            yield FileMovedEvent(renamed_path, full_path)


def generate_sub_created_events(src_dir_path):
    """Generates an event list of :class:`DirCreatedEvent` and
    :class:`FileCreatedEvent` objects for all the files and directories within
    the given moved directory that were moved along with the directory.

    :param src_dir_path:
        The source path of the created directory.
    :returns:
        An iterable of file system events of type :class:`DirCreatedEvent` and
        :class:`FileCreatedEvent`.
    """
    for root, directories, filenames in os.walk(src_dir_path):
        for directory in directories:
            yield DirCreatedEvent(os.path.join(root, directory))
        for filename in filenames:
            yield FileCreatedEvent(os.path.join(root, filename))