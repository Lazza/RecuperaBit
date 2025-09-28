"""Filesystem-independent algorithmic logic."""

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


import bisect
import logging
import os
from pathlib import Path
import sys
import time
import types
from typing import TYPE_CHECKING, Dict, List, Optional, Union, Iterator, Set, TypeVar, Generic

T = TypeVar('T')

if TYPE_CHECKING:
    from .fs.core_types import File, Partition


class SparseList(Generic[T]):
    """List which only stores values at some places."""
    def __init__(self, data: Optional[Dict[int, T]] = None, default: Optional[T] = None) -> None:
        self.keys: List[int] = []  # This is always kept in order
        self.elements: Dict[int, T] = {}
        self.default: Optional[T] = default
        if data is not None:
            self.keys = sorted(data)
            self.elements.update(data)

    def __len__(self) -> int:
        try:
            return self.keys[-1] + 1
        except IndexError:
            return 0

    def __getitem__(self, index: int) -> Optional[T]:
        return self.elements.get(index, self.default)

    def __setitem__(self, index: int, item: T) -> None:
        if item == self.default:
            if index in self.elements:
                del self.elements[index]
                del self.keys[bisect.bisect_left(self.keys, index)]
        else:
            if index not in self.elements:
                bisect.insort(self.keys, index)
            self.elements[index] = item

    def __contains__(self, element: T) -> bool:
        return element in self.elements.values()

    def __iter__(self) -> Iterator[int]:
        return self.keys.__iter__()

    def __repr__(self) -> str:
        elems = []
        prevk = 0
        if len(self.elements) > 0:
            k = self.keys[0]
            elems.append(str(k) + ' -> ' + repr(self.elements[k]))
            prevk = self.keys[0]
        for i in range(1, len(self.elements)):
            nextk = self.keys[i]
            if nextk <= prevk + 2:
                while prevk < nextk - 1:
                    elems.append('__')
                    prevk += 1
                elems.append(repr(self.elements[nextk]))
            else:
                elems.append('\n... ' + str(nextk) + ' -> ' +
                             repr(self.elements[nextk]))
            prevk = nextk

        return '[' + ', '.join(elems) + ']'

    def iterkeys(self) -> Iterator[int]:
        """An iterator over the keys of actual elements."""
        return self.__iter__()

    def iterkeys_rev(self) -> Iterator[int]:
        """An iterator over the keys of actual elements (reversed)."""
        i = len(self.keys)
        while i > 0:
            i -= 1
            yield self.keys[i]

    def itervalues(self) -> Iterator[T]:
        """An iterator over the elements."""
        for k in self.keys:
            yield self.elements[k]

    def wipe_interval(self, bottom: int, top: int) -> None:
        """Remove elements between bottom and top."""
        new_keys = set()
        if bottom > top:
            for k in self.keys:
                if top <= k < bottom:
                    new_keys.add(k)
                else:
                    del self.elements[k]
        else:
            for k in self.keys:
                if bottom <= k < top:
                    del self.elements[k]
                else:
                    new_keys.add(k)
        self.keys = sorted(new_keys)


def preprocess_pattern(pattern: SparseList[T]) -> Dict[T, List[int]]:
    """Preprocess a SparseList for approximate string matching.

    This function performs preprocessing for the Baeza-Yates--Perleberg
    fast and practical approximate string matching algorithm."""
    result: Dict[T, List[int]] = {}
    length = pattern.__len__()
    for k in pattern:
        name = pattern[k]
        if name not in result:
            result[name] = [length-k-1]
        elif name != result[name][-1]:
            result[name].append(length-k-1)
    return result


def approximate_matching(records: SparseList[T], pattern: SparseList[T], stop: int, k: int = 1) -> Optional[List[Union[Set[int], int, float]]]:
    """Find the best match for a given pattern.

    The Baeza-Yates--Perleberg algorithm requires a preprocessed pattern. This
    function takes as input a SparseList of records and pattern that will be
    preprocessed. The records in the SparseList should be formed by single
    elements. If they have another shape, e.g. tuples of the form
    (namespace, name), the get function can be used to tell the algorithm how
    to access them. k is the minimum value for support."""

    msize = pattern.__len__()
    if records.__len__() == 0 or msize == 0:
        return None

    lookup = preprocess_pattern(pattern)
    count: SparseList[int] = SparseList(default=0)
    match_offsets: Set[int] = set()

    i = 0
    j = 0   # previous value of i

    # logging.debug('Starting approximate matching up to %i', stop)
    # Loop only on indexes where there are elements
    for i in records:
        if i > stop+msize-1:
            break

        # zero-out the parts that were skipped
        count.wipe_interval(j % msize, i % msize)
        j = i

        offsets = set(lookup.get(records[i], []))
        for off in offsets:
            count[(i + off) % msize] += 1
            score = count[(i + off) % msize]
            if score == k:
                match_offsets.add(i+off-msize+1)
            if score > k:
                k = score
                match_offsets = set([i+off-msize+1])

    if len(match_offsets):
        logging.debug(
            'Found MATCH in positions {} '
            'with weight {} ({}%)'.format(
                match_offsets, k,
                k * 100.0 / len(pattern.keys)
            )
        )
        return [match_offsets, k, float(k) / len(pattern.keys)]
    else:
        # logging.debug('No match found')
        return None


def makedirs(path: str | Path) -> bool:
    """Make directories if they do not exist."""
    path = Path(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        logging.error(f"makedirs: {path} already exists and is not a directory")
    except OSError:
        _, value, _ = sys.exc_info()
        logging.error(value)
        return False
    return True


def recursive_restore(node: 'File', part: 'Partition', outputdir: str, make_dirs: bool = True) -> None:
    """Restore a directory structure starting from a file node."""
    # Use a stack for iterative depth-first traversal
    stack = [node]
    
    while stack:
        current_node = stack.pop()
        
        logging.info(u'Restoring #%s %s', current_node.index, current_node.name)
        
        try:
            parent_path = str(
                part[current_node.parent].full_path(part) if current_node.parent is not None
                else ''
            )

            file_path = Path(parent_path) / current_node.name
            restore_path = Path(outputdir) / file_path

            try:
                content = current_node.get_content(part)
            except NotImplementedError:
                logging.error(u'Restore of #%s %s is not supported', current_node.index, file_path)
                content = None

            is_directory = current_node.is_directory or len(current_node.children) > 0

            if make_dirs:
                restore_path.parent.mkdir(parents=True, exist_ok=True)

            if is_directory:
                if not makedirs(restore_path):
                    continue

            if is_directory and content is not None:
                logging.warning(u'Directory %s has data content!', file_path)
                restore_path = Path(str(restore_path) + '_recuperabit_content')

            try:
                if content is not None:
                    with open(restore_path, 'wb') as outfile:
                        if isinstance(content, types.GeneratorType):
                            for piece in content:
                                outfile.write(piece)
                        else:
                            outfile.write(content)
                else:
                    if not is_directory:
                        # Empty file
                        open(restore_path, 'wb').close()
            except IOError:
                logging.error(u'IOError when trying to create %s', restore_path)

            try:
                # Restore Modification + Access time
                mtime, atime, _ = current_node.get_mac()
                if mtime is not None:
                    atime = time.mktime(atime.astimezone().timetuple())
                    mtime = time.mktime(mtime.astimezone().timetuple())
                    os.utime(restore_path, (atime, mtime))
            except IOError:
                logging.error(u'IOError while setting atime and mtime of %s', restore_path)

            # Add children to stack for processing (in reverse order to maintain depth-first traversal)
            if is_directory:
                for child in current_node.children:
                    if not child.ignore():
                        logging.info(u'Adding child file %s to stack', child.name)
                        stack.append(child)
                    else:
                        logging.info(u'Skipping ignored file %s', child.name)

        except Exception as e:
            logging.error(u'Error restoring #%s %s: %s', current_node.index, current_node.name, e)