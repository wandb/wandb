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
Utility collections or "bricks".

:module: watchdog.utils.bricks
:author: yesudeep@google.com (Yesudeep Mangalapilly)
:author: lalinsky@gmail.com (Lukáš Lalinský)
:author: python@rcn.com (Raymond Hettinger)

Classes
=======
.. autoclass:: OrderedSetQueue
   :members:
   :show-inheritance:
   :inherited-members:

.. autoclass:: OrderedSet

"""

import sys
import collections
from .compat import queue

class SkipRepeatsQueue(queue.Queue):

    """Thread-safe implementation of an special queue where a
    put of the last-item put'd will be dropped.

    The implementation leverages locking already implemented in the base class
    redefining only the primitives.

    Queued items must be immutable and hashable so that they can be used
    as dictionary keys. You must implement **only read-only properties** and
    the :meth:`Item.__hash__()`, :meth:`Item.__eq__()`, and
    :meth:`Item.__ne__()` methods for items to be hashable.

    An example implementation follows::

        class Item(object):
            def __init__(self, a, b):
                self._a = a
                self._b = b

            @property
            def a(self):
                return self._a

            @property
            def b(self):
                return self._b

            def _key(self):
                return (self._a, self._b)

            def __eq__(self, item):
                return self._key() == item._key()

            def __ne__(self, item):
                return self._key() != item._key()

            def __hash__(self):
                return hash(self._key())

    based on the OrderedSetQueue below
    """

    def _init(self, maxsize):
        queue.Queue._init(self, maxsize)
        self._last_item = None

    def _put(self, item):
        if item != self._last_item:
            queue.Queue._put(self, item)
            self._last_item = item
        else:
            # `put` increments `unfinished_tasks` even if we did not put
            # anything into the queue here
            self.unfinished_tasks -= 1

    def _get(self):
        item = queue.Queue._get(self)
        if item is self._last_item:
            self._last_item = None
        return item


class OrderedSetQueue(queue.Queue):

    """Thread-safe implementation of an ordered set queue.

    Disallows adding a duplicate item while maintaining the
    order of items in the queue. The implementation leverages
    locking already implemented in the base class
    redefining only the primitives. Since the internal queue
    is not replaced, the order is maintained. The set is used
    merely to check for the existence of an item.

    Queued items must be immutable and hashable so that they can be used
    as dictionary keys. You must implement **only read-only properties** and
    the :meth:`Item.__hash__()`, :meth:`Item.__eq__()`, and
    :meth:`Item.__ne__()` methods for items to be hashable.

    An example implementation follows::

        class Item(object):
            def __init__(self, a, b):
                self._a = a
                self._b = b

            @property
            def a(self):
                return self._a

            @property
            def b(self):
                return self._b

            def _key(self):
                return (self._a, self._b)

            def __eq__(self, item):
                return self._key() == item._key()

            def __ne__(self, item):
                return self._key() != item._key()

            def __hash__(self):
                return hash(self._key())

    :author: lalinsky@gmail.com (Lukáš Lalinský)
    :url: http://stackoverflow.com/questions/1581895/how-check-if-a-task-is-already-in-python-queue
    """

    def _init(self, maxsize):
        queue.Queue._init(self, maxsize)
        self._set_of_items = set()

    def _put(self, item):
        if item not in self._set_of_items:
            queue.Queue._put(self, item)
            self._set_of_items.add(item)
        else:
            # `put` increments `unfinished_tasks` even if we did not put
            # anything into the queue here
            self.unfinished_tasks -= 1

    def _get(self):
        item = queue.Queue._get(self)
        self._set_of_items.remove(item)
        return item


if sys.version_info >= (2, 6, 0):
    KEY, PREV, NEXT = list(range(3))

    class OrderedSet(collections.MutableSet):

        """
        Implementation based on a doubly-linked link and an internal dictionary.
        This design gives :class:`OrderedSet` the same big-Oh running times as
        regular sets including O(1) adds, removes, and lookups as well as
        O(n) iteration.

        .. ADMONITION:: Implementation notes

                Runs on Python 2.6 or later (and runs on Python 3.0 or later
                without any modifications).

        :author: python@rcn.com (Raymond Hettinger)
        :url: http://code.activestate.com/recipes/576694/
        """

        def __init__(self, iterable=None):
            self.end = end = []
            end += [None, end, end]         # sentinel node for doubly linked list
            self.map = {}                   # key --> [key, prev, next]
            if iterable is not None:
                self |= iterable

        def __len__(self):
            return len(self.map)

        def __contains__(self, key):
            return key in self.map

        def add(self, key):
            if key not in self.map:
                end = self.end
                curr = end[PREV]
                curr[NEXT] = end[PREV] = self.map[key] = [key, curr, end]

        def discard(self, key):
            if key in self.map:
                key, prev, _next = self.map.pop(key)
                prev[NEXT] = _next
                _next[PREV] = prev

        def __iter__(self):
            end = self.end
            curr = end[NEXT]
            while curr is not end:
                yield curr[KEY]
                curr = curr[NEXT]

        def __reversed__(self):
            end = self.end
            curr = end[PREV]
            while curr is not end:
                yield curr[KEY]
                curr = curr[PREV]

        def pop(self, last=True):
            if not self:
                raise KeyError('set is empty')
            key = next(reversed(self)) if last else next(iter(self))
            self.discard(key)
            return key

        def __repr__(self):
            if not self:
                return '%s()' % (self.__class__.__name__,)
            return '%s(%r)' % (self.__class__.__name__, list(self))

        def __eq__(self, other):
            if isinstance(other, OrderedSet):
                return len(self) == len(other) and list(self) == list(other)
            return set(self) == set(other)

        def __del__(self):
            self.clear()                    # remove circular references
