"""Recuperabit Core Types.

This module contains the class declarations of all objects which are used in
the Recuperabit meta file system. Each plug-in is supposed to extend the File
and DiskScanner classes with subclasses implementing the missing methods."""

# RecuperaBit
# Copyright 2014-2021 Andrea Lazzarotto
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
from typing import Optional, Dict, Set, List, Tuple, Union, Any, Iterator
from datetime import datetime

from .constants import sector_size

from ..utils import readable_bytes


class File(object):
    """Filesystem-independent representation of a file. Aka Node."""
    def __init__(self, index: Union[int, str], name: str, size: Optional[int], is_directory: bool = False,
                 is_deleted: bool = False, is_ghost: bool = False) -> None:
        self.index: Union[int, str] = index
        self.name: str = name
        self.size: Optional[int] = size
        self.is_directory: bool = is_directory
        self.is_deleted: bool = is_deleted
        self.is_ghost: bool = is_ghost
        self.parent: Optional[Union[int, str]] = None
        self.mac: Dict[str, Optional[datetime]] = {
            'modification': None,
            'access': None,
            'creation': None
        }
        self.children: Set['File'] = set()
        self.children_names: Set[str] = set()     # Avoid name clashes breaking restore
        self.offset: Optional[int] = None  # Offset from beginning of disk

    def set_parent(self, parent: Optional[Union[int, str]]) -> None:
        """Set a pointer to the parent directory."""
        self.parent = parent

    def set_mac(self, modification: Optional[datetime], access: Optional[datetime], creation: Optional[datetime]) -> None:
        """Set the modification, access and creation times."""
        self.mac['modification'] = modification
        self.mac['access'] = access
        self.mac['creation'] = creation

    def get_mac(self) -> List[Optional[datetime]]:
        """Get the modification, access and creation times."""
        keys = ('modification', 'access', 'creation')
        return [self.mac[k] for k in keys]

    def set_offset(self, offset: Optional[int]) -> None:
        """Set the offset of the file record with respect to the disk image."""
        self.offset = offset

    def get_offset(self) -> Optional[int]:
        """Get the offset of the file record with respect to the disk image."""
        return self.offset

    def add_child(self, node: 'File') -> None:
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

    def full_path(self, part: 'Partition') -> str:
        """Return the full path of this file."""
        if self.parent is not None:
            parent = part[self.parent]
            return os.path.join(parent.full_path(part), self.name)
        else:
            return self.name

    def get_content(self, partition: 'Partition') -> Optional[Union[bytes, Iterator[bytes]]]:
        # pylint: disable=W0613
        """Extract the content of the file.

        This method is intentionally not implemented because it depends on each
        plug-in for a specific file system."""
        if self.is_directory or self.is_ghost:
            return None
        raise NotImplementedError

    # pylint: disable=R0201
    def ignore(self) -> bool:
        """The following method is used by the restore procedure to check
        files that should not be recovered. For example, in NTFS file
        $BadClus:$Bad shall not be recovered because it creates an output
        with the same size as the partition (usually many GBs)."""
        return False

    def __repr__(self) -> str:
        return (
            u'File(#%s, ^^%s^^, %s, offset = %s sectors)' %
            (self.index, self.parent, self.name, self.offset)
        )


class Partition(object):
    """Simplified representation of the contents of a partition.

    Parameter root_id represents the identifier assigned to the root directory
    of a partition. This can be file system dependent."""
    def __init__(self, fs_type: str, root_id: Union[int, str], scanner: 'DiskScanner') -> None:
        self.fs_type: str = fs_type
        self.root_id: Union[int, str] = root_id
        self.size: Optional[int] = None
        self.offset: Optional[int] = None
        self.root: Optional[File] = None
        self.lost: File = File(-1, 'LostFiles', 0, is_directory=True, is_ghost=True)
        self.files: Dict[Union[int, str], File] = {}
        self.recoverable: bool = False
        self.scanner: 'DiskScanner' = scanner

    def add_file(self, node: File) -> None:
        """Insert a new file in the partition."""
        index = node.index
        self.files[index] = node

    def set_root(self, node: File) -> None:
        """Set the root directory."""
        if not node.is_directory:
            raise TypeError('Not a directory')
        self.root = node
        self.root.set_parent(None)

    def set_size(self, size: int) -> None:
        """Set the (estimated) size of the partition."""
        self.size = size

    def set_offset(self, offset: int) -> None:
        """Set the offset from the beginning of the disk."""
        self.offset = offset

    def set_recoverable(self, recoverable: bool) -> None:
        """State if the partition contents are also recoverable."""
        self.recoverable = recoverable

    def rebuild(self) -> None:
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
    def additional_repr(self) -> List[Tuple[str, Any]]:
        """Return additional values to show in the string representation."""
        return []

    def __repr__(self) -> str:
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

    def __getitem__(self, index: Union[int, str]) -> File:
        if index in self.files:
            return self.files[index]
        if index == self.lost.index:
            return self.lost
        raise KeyError

    def get(self, index: Union[int, str], default: Optional[File] = None) -> Optional[File]:
        """Get a file or the special LostFiles directory."""
        try:
            return self.__getitem__(index)
        except KeyError:
            return default


class DiskScanner(object):
    """Abstract stub for the implementation of disk scanners."""
    def __init__(self, pointer: Any) -> None:
        self.image: Any = pointer

    def get_image(self) -> Any:
        """Return the image reference."""
        return self.image

    @staticmethod
    def get_image(scanner: 'DiskScanner') -> Any:
        """Static method to get image from scanner instance."""
        return scanner.image

    def feed(self, index: int, sector: bytes) -> Optional[str]:
        """Feed a new sector."""
        raise NotImplementedError

    def get_partitions(self) -> Dict[int, Partition]:
        """Get a list of the found partitions."""
        raise NotImplementedError
