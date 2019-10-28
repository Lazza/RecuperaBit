"""Filesystem-independent algorithmic logic."""

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


import bisect
import codecs
import logging
import os
import os.path
import sys

from utils import tiny_repr


class SparseList(object):
    """List which only stores values at some places."""
    def __init__(self, data=None, default=None):
        self.keys = []  # This is always kept in order
        self.elements = {}
        self.default = default
        if data is not None:
            self.keys = sorted(data.iterkeys())
            self.elements.update(data)

    def __len__(self):
        try:
            return self.keys[-1] + 1
        except IndexError:
            return 0

    def __getitem__(self, index):
        return self.elements.get(index, self.default)

    def __setitem__(self, index, item):
        if item == self.default:
            if index in self.elements:
                del self.elements[index]
                del self.keys[bisect.bisect_left(self.keys, index)]
        else:
            if index not in self.elements:
                bisect.insort(self.keys, index)
            self.elements[index] = item

    def __contains__(self, element):
        return element in self.elements.itervalues()

    def __iter__(self):
        return self.keys.__iter__()

    def __repr__(self):
        elems = []
        prevk = 0
        if len(self.elements) > 0:
            k = self.keys[0]
            elems.append(str(k) + ' -> ' + tiny_repr(self.elements[k]))
            prevk = self.keys[0]
        for i in xrange(1, len(self.elements)):
            nextk = self.keys[i]
            if nextk <= prevk + 2:
                while prevk < nextk - 1:
                    elems.append('__')
                    prevk += 1
                elems.append(tiny_repr(self.elements[nextk]))
            else:
                elems.append('\n... ' + str(nextk) + ' -> ' +
                             tiny_repr(self.elements[nextk]))
            prevk = nextk

        return '[' + ', '.join(elems) + ']'

    def iterkeys(self):
        """An iterator over the keys of actual elements."""
        return self.__iter__()

    def iterkeys_rev(self):
        """An iterator over the keys of actual elements (reversed)."""
        i = len(self.keys)
        while i > 0:
            i -= 1
            yield self.keys[i]

    def itervalues(self):
        """An iterator over the elements."""
        for k in self.keys:
            yield self.elements[k]

    def wipe_interval(self, bottom, top):
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


def preprocess_pattern(pattern):
    """Preprocess a SparseList for approximate string matching.

    This function performs preprocessing for the Baeza-Yates--Perleberg
    fast and practical approximate string matching algorithm."""
    result = {}
    length = pattern.__len__()
    for k in pattern:
        name = pattern[k]
        if name not in result:
            result[name] = [length-k-1]
        elif name != result[name][-1]:
            result[name].append(length-k-1)
    return result


def approximate_matching(records, pattern, stop, k=1):
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
    count = SparseList(default=0)
    match_offsets = set()

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


def makedirs(path):
    """Make directories if they do not exist."""
    try:
        os.makedirs(path)
    except OSError:
        _, value, _ = sys.exc_info()
        # The directory already exists = no problem
        if value.errno != 17:
            logging.error(value)
            return False
    return True


def recursive_restore(node, part, outputdir, make_dirs=True):
    """Restore a directory structure starting from a file node."""
    parent_path = unicode(
        part[node.parent].full_path(part) if node.parent is not None
        else ''
    )

    file_path = os.path.join(parent_path, node.name)
    restore_parent_path = os.path.join(outputdir, parent_path)
    restore_path = os.path.join(outputdir, file_path)

    try:
        content = node.get_content(part)
    except NotImplementedError:
        logging.error(u'Restore of #%s %s is not supported', node.index,
                      file_path)
        content = None

    if make_dirs:
        if not makedirs(restore_parent_path):
            return

    is_directory = node.is_directory or len(node.children) > 0

    if is_directory:
        logging.info(u'Restoring #%s %s', node.index, file_path)
        if not makedirs(restore_path):
            return

    if is_directory and content is not None:
        logging.warning(u'Directory %s has data content!', file_path)
        restore_path += '_recuperabit_content'

    try:
        if content is not None:
            logging.info(u'Restoring #%s %s', node.index, file_path)
            with codecs.open(restore_path, 'wb') as outfile:
                if hasattr(content, '__iter__'):
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

    if is_directory:
        for child in node.children:
            if not child.ignore():
                recursive_restore(child, part, outputdir, make_dirs=False)
            else:
                logging.info(u'Skipping ignored file {}'.format(child))
