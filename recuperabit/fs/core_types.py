"""Recuperabit Core Types.

This module contains the class declarations of all objects which are used in
the Recuperabit meta file system. Each plug-in is supposed to extend the File
and DiskScanner classes with subclasses implementing the missing methods."""

# RecuperaBit
# Copyright 2014-2017 Andrea Lazzarotto
#
# This file is part of RecuperaBit.
#
# RecuperaBit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# RecuperaBit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with RecuperaBit. If not, see <http://www.gnu.org/licenses/>.


import logging
import os.path

from constants import sector_size

from ..utils import readable_bytes


class File(object):
    """Filesystem-independent representation of a file."""
    def __init__(self, index, name, size, is_directory=False,
                 is_deleted=False, is_ghost=False):
        self.index = index
        self.name = name
        self.size = size
        self.is_directory = is_directory
        self.is_deleted = is_deleted
        self.is_ghost = is_ghost
        self.parent = None
        self.mac = {
            'modification': None,
            'access': None,
            'creation': None
        }
        self.children = set()
        self.children_names = set()     # Avoid name clashes breaking restore
        self.offset = None  # Offset from beginning of disk

    def set_parent(self, parent):
        """Set a pointer to the parent directory."""
        self.parent = parent

    def set_mac(self, modification, access, creation):
        """Set the modification, access and creation times."""
        self.mac['modification'] = modification
        self.mac['access'] = access
        self.mac['creation'] = creation

    def get_mac(self):
        """Get the modification, access and creation times."""
        keys = ('modification', 'access', 'creation')
        return [self.mac[k] for k in keys]

    def set_offset(self, offset):
        """Set the offset of the file record with respect to the disk image."""
        self.offset = offset

    def get_offset(self):
        """Get the offset of the file record with respect to the disk image."""
        return self.offset

    def add_child(self, node):
        """Add a new child to this directory."""
        original_name = node.name
        i = 0
        # Check for multiple rebuilds
        if node in self.children:
            return
        # Avoid name clashes
        while node.name in self.children_names:
            node.name = original_name + '_%03d' % i
            i += 1
        if node.name != original_name:
            logging.warning(u'Renamed {} from {}'.format(node, original_name))
        self.children.add(node)
        self.children_names.add(node.name)

    def full_path(self, part):
        """Return the full path of this file."""
        if self.parent is not None:
            parent = part[self.parent]
            return os.path.join(parent.full_path(part), unicode(self.name))
        else:
            return unicode(self.name)

    def get_content(self, partition):
        # pylint: disable=W0613
        """Extract the content of the file.

        This method is intentionally not implemented because it depends on each
        plug-in for a specific file system."""
        if self.is_directory or self.is_ghost:
            return None
        raise NotImplementedError

    # pylint: disable=R0201
    def ignore(self):
        """The following method is used by the restore procedure to check
        files that should not be recovered. For example, in NTFS file
        $BadClus:$Bad shall not be recovered because it creates an output
        with the same size as the partition (usually many GBs)."""
        return False

    def __repr__(self):
        return (
            u'File(#%s, ^^%s^^, %s, offset = %s sectors)' %
            (self.index, self.parent, self.name, self.offset)
        )


class Partition(object):
    """Simplified representation of the contents of a partition.

    Parameter root_id represents the identifier assigned to the root directory
    of a partition. This can be file system dependent."""
    def __init__(self, fs_type, root_id, scanner):
        self.fs_type = fs_type
        self.root_id = root_id
        self.size = None
        self.offset = None
        self.root = None
        self.lost = File(-1, 'LostFiles', 0, is_directory=True, is_ghost=True)
        self.files = {}
        self.recoverable = False
        self.scanner = scanner

    def add_file(self, node):
        """Insert a new file in the partition."""
        index = node.index
        self.files[index] = node

    def set_root(self, node):
        """Set the root directory."""
        if not node.is_directory:
            raise TypeError('Not a directory')
        self.root = node
        self.root.set_parent(None)

    def set_size(self, size):
        """Set the (estimated) size of the partition."""
        self.size = size

    def set_offset(self, offset):
        """Set the offset from the beginning of the disk."""
        self.offset = offset

    def set_recoverable(self, recoverable):
        """State if the partition contents are also recoverable."""
        self.recoverable = recoverable

    def rebuild(self):
        """Rebuild the partition structure.

        This method processes the contents of files and it rebuilds the
        directory tree as accurately as possible."""
        root_id = self.root_id
        rootname = 'Root'

        if root_id not in self.files:
            self.files[root_id] = File(
                root_id, rootname, 0, is_directory=True, is_ghost=True
            )

        # Convert keys to list to avoid RuntimeError
        for identifier in list(self.files):
            node = self.files[identifier]
            if node.index == root_id:
                self.set_root(node)
                node.name = rootname
            else:
                parent_id = node.parent
                exists = parent_id is not None
                valid = parent_id in self.files
                if exists and valid:
                    parent_node = self.files[parent_id]
                elif exists and not valid:
                    parent_node = File(parent_id, 'Dir_' + str(parent_id),
                                       0, is_directory=True, is_ghost=True)
                    parent_node.set_parent(-1)
                    self.files[parent_id] = parent_node
                    self.lost.add_child(parent_node)
                else:
                    parent_node = self.lost
                    node.set_parent(-1)
                parent_node.add_child(node)
        return

    # pylint: disable=R0201
    def additional_repr(self):
        """Return additional values to show in the string representation."""
        return []

    def __repr__(self):
        size = (
            readable_bytes(self.size * sector_size)
            if self.size is not None else '??? b'
        )
        data = [
            ('Offset', self.offset),
            (
                'Offset (b)',
                self.offset * sector_size
                if self.offset is not None else None
            ),
        ]
        data += self.additional_repr()
        return u'Partition (%s, %s, %d files,%s %s)' % (
            self.fs_type,
            size,
            len(self.files),
            ' Recoverable,' if self.recoverable else '',
            ', '.join(a+': '+str(b) for a, b in data)
        )

    def __getitem__(self, index):
        if index in self.files:
            return self.files[index]
        if index == self.lost.index:
            return self.lost
        raise KeyError

    def get(self, index, default=None):
        """Get a file or the special LostFiles directory."""
        try:
            return self.__getitem__(index)
        except KeyError:
            return default


class DiskScanner(object):
    """Abstract stub for the implementation of disk scanners."""
    def __init__(self, pointer):
        self.image = pointer

    def get_image(self):
        """Return the image reference."""
        return self.image

    def feed(self, index, sector):
        """Feed a new sector."""
        raise NotImplementedError

    def get_partitions(self):
        """Get a list of the found partitions."""
        raise NotImplementedError
