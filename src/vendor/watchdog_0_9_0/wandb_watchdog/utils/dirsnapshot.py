#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2011 Yesudeep Mangalapilly <yesudeep@gmail.com>
# Copyright 2012 Google, Inc.
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
:module: watchdog.utils.dirsnapshot
:synopsis: Directory snapshots and comparison.
:author: yesudeep@google.com (Yesudeep Mangalapilly)

.. ADMONITION:: Where are the moved events? They "disappeared"

        This implementation does not take partition boundaries
        into consideration. It will only work when the directory
        tree is entirely on the same file system. More specifically,
        any part of the code that depends on inode numbers can
        break if partition boundaries are crossed. In these cases,
        the snapshot diff will represent file/directory movement as
        created and deleted events.

Classes
-------
.. autoclass:: DirectorySnapshot
   :members:
   :show-inheritance:

.. autoclass:: DirectorySnapshotDiff
   :members:
   :show-inheritance:

"""

import errno
import os
from stat import S_ISDIR
from wandb_watchdog.utils import stat as default_stat


class DirectorySnapshotDiff(object):
    """
    Compares two directory snapshots and creates an object that represents
    the difference between the two snapshots.

    :param ref:
        The reference directory snapshot.
    :type ref:
        :class:`DirectorySnapshot`
    :param snapshot:
        The directory snapshot which will be compared
        with the reference snapshot.
    :type snapshot:
        :class:`DirectorySnapshot`
    """
    
    def __init__(self, ref, snapshot):
        created = snapshot.paths - ref.paths
        deleted = ref.paths - snapshot.paths
        
        # check that all unchanged paths have the same inode
        for path in ref.paths & snapshot.paths:
            if ref.inode(path) != snapshot.inode(path):
                created.add(path)
                deleted.add(path)
        
        # find moved paths
        moved = set()
        for path in set(deleted):
            inode = ref.inode(path)
            new_path = snapshot.path(inode)
            if new_path:
                # file is not deleted but moved
                deleted.remove(path)
                moved.add((path, new_path))
        
        for path in set(created):
            inode = snapshot.inode(path)
            old_path = ref.path(inode)
            if old_path:
                created.remove(path)
                moved.add((old_path, path))
        
        # find modified paths
        # first check paths that have not moved
        modified = set()
        for path in ref.paths & snapshot.paths:
            if ref.inode(path) == snapshot.inode(path):
                if ref.mtime(path) != snapshot.mtime(path):
                    modified.add(path)
        
        for (old_path, new_path) in moved:
            if ref.mtime(old_path) != snapshot.mtime(new_path):
                modified.add(old_path)
        
        self._dirs_created = [path for path in created if snapshot.isdir(path)]
        self._dirs_deleted = [path for path in deleted if ref.isdir(path)]
        self._dirs_modified = [path for path in modified if ref.isdir(path)]
        self._dirs_moved = [(frm, to) for (frm, to) in moved if ref.isdir(frm)]
        
        self._files_created = list(created - set(self._dirs_created))
        self._files_deleted = list(deleted - set(self._dirs_deleted))
        self._files_modified = list(modified - set(self._dirs_modified))
        self._files_moved = list(moved - set(self._dirs_moved))
    
    @property
    def files_created(self):
        """List of files that were created."""
        return self._files_created

    @property
    def files_deleted(self):
        """List of files that were deleted."""
        return self._files_deleted

    @property
    def files_modified(self):
        """List of files that were modified."""
        return self._files_modified

    @property
    def files_moved(self):
        """
        List of files that were moved.

        Each event is a two-tuple the first item of which is the path
        that has been renamed to the second item in the tuple.
        """
        return self._files_moved

    @property
    def dirs_modified(self):
        """
        List of directories that were modified.
        """
        return self._dirs_modified

    @property
    def dirs_moved(self):
        """
        List of directories that were moved.

        Each event is a two-tuple the first item of which is the path
        that has been renamed to the second item in the tuple.
        """
        return self._dirs_moved

    @property
    def dirs_deleted(self):
        """
        List of directories that were deleted.
        """
        return self._dirs_deleted

    @property
    def dirs_created(self):
        """
        List of directories that were created.
        """
        return self._dirs_created

class DirectorySnapshot(object):
    """
    A snapshot of stat information of files in a directory.

    :param path:
        The directory path for which a snapshot should be taken.
    :type path:
        ``str``
    :param recursive:
        ``True`` if the entire directory tree should be included in the
        snapshot; ``False`` otherwise.
    :type recursive:
        ``bool``
    :param walker_callback:
        .. deprecated:: 0.7.2
    :param stat:
        Use custom stat function that returns a stat structure for path.
        Currently only st_dev, st_ino, st_mode and st_mtime are needed.
        
        A function with the signature ``walker_callback(path, stat_info)``
        which will be called for every entry in the directory tree.
    :param listdir:
        Use custom listdir function. See ``os.listdir`` for details.
    """
    
    def __init__(self, path, recursive=True,
                 walker_callback=(lambda p, s: None),
                 stat=default_stat,
                 listdir=os.listdir):
        self._stat_info = {}
        self._inode_to_path = {}
        
        st = stat(path)
        self._stat_info[path] = st
        self._inode_to_path[(st.st_ino, st.st_dev)] = path

        def walk(root):
            try:
                paths = [os.path.join(root, name) for name in listdir(root)]
            except OSError as e:
                # Directory may have been deleted between finding it in the directory
                # list of its parent and trying to delete its contents. If this
                # happens we treat it as empty.
                if e.errno == errno.ENOENT:
                    return
                else:
                    raise
            entries = []
            for p in paths:
                try:
                    entries.append((p, stat(p)))
                except OSError:
                    continue
            for _ in entries:
                yield _
            if recursive:
                for path, st in entries:
                    if S_ISDIR(st.st_mode):
                        for _ in walk(path):
                            yield _

        for p, st in walk(path):
            i = (st.st_ino, st.st_dev)
            self._inode_to_path[i] = p
            self._stat_info[p] = st
            walker_callback(p, st)

    @property
    def paths(self):
        """
        Set of file/directory paths in the snapshot.
        """
        return set(self._stat_info.keys())
    
    def path(self, id):
        """
        Returns path for id. None if id is unknown to this snapshot.
        """
        return self._inode_to_path.get(id)
    
    def inode(self, path):
        """ Returns an id for path. """
        st = self._stat_info[path]
        return (st.st_ino, st.st_dev)
    
    def isdir(self, path):
        return S_ISDIR(self._stat_info[path].st_mode)
    
    def mtime(self, path):
        return self._stat_info[path].st_mtime
    
    def stat_info(self, path):
        """
        Returns a stat information object for the specified path from
        the snapshot.

        Attached information is subject to change. Do not use unless
        you specify `stat` in constructor. Use :func:`inode`, :func:`mtime`,
        :func:`isdir` instead.

        :param path:
            The path for which stat information should be obtained
            from a snapshot.
        """
        return self._stat_info[path]

    def __sub__(self, previous_dirsnap):
        """Allow subtracting a DirectorySnapshot object instance from
        another.

        :returns:
            A :class:`DirectorySnapshotDiff` object.
        """
        return DirectorySnapshotDiff(previous_dirsnap, self)
    
    def __str__(self):
        return self.__repr__()
    
    def __repr__(self):
        return str(self._stat_info)
