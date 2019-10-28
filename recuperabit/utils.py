"""Collection of utility functions."""

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
import pprint
import string
import sys
import time
import unicodedata

from fs.constants import sector_size

printer = pprint.PrettyPrinter(indent=4)
all_chars = (unichr(i) for i in xrange(sys.maxunicode))
unicode_printable = set(
    c for c in all_chars
    if not unicodedata.category(c)[0].startswith('C')
)
ascii_printable = set(string.printable[:-5])


def sectors(image, offset, size, bsize=sector_size, fill=True):
    """Read from a file descriptor."""
    read = True
    try:
        image.seek(offset * bsize)
    except IOError:
        read = False
    if read:
        try:
            dump = image.read(size * bsize)
        except (IOError, MemoryError):
            logging.warning(
                "Cannot read sector(s). Filling with 0x00. Offset: {} Size: "
                "{} Bsize: {}".format(offset, size, bsize)
            )
            read = False
    if not read:
        if fill:
            dump = size * bsize * '\x00'
        else:
            return None
    return bytearray(dump)


def signedbytes(data):
    """Convert a bytearray into an integer, considering the first bit as
    sign. The data must be Big-endian."""
    if data[0] & 0x80:
        inverted = bytearray(~d % 256 for d in data)
        return -signedbytes(inverted) - 1

    encoded = str(data).encode('hex')
    return int(encoded, 16)


def unixtime(dtime):
    """Convert datetime to UNIX epoch."""
    if dtime is None:
        return 0
    try:
        return time.mktime(dtime.timetuple())
    except ValueError:
        return 0


def unpack(data, fmt):
    """Extract formatted information from a string of bytes."""
    result = {}
    for label, description in fmt:
        formatter, lower, higher = description
        # If lower is a function, then apply it
        low = lower(result) if callable(lower) else lower
        high = higher(result) if callable(higher) else higher

        if low is None or high is None:
            result[label] = None
            continue

        if callable(formatter):
            result[label] = formatter(data[low:high+1])
        else:
            if formatter == 's':
                result[label] = str(data[low:high+1])
            if formatter.startswith('utf'):
                result[label] = data[low:high+1].decode(formatter)
            if formatter.endswith('i') and len(formatter) < 4:
                # Use little-endian by default. Big-endian with >i.
                # Force sign-extension of first bit with >+i / +i.
                step = 1 if formatter.startswith('>') else -1
                chunk = data[low:high+1]
                if len(chunk):
                    if '+' in formatter:
                        result[label] = signedbytes(chunk[::step])
                    else:
                        encoded = str(chunk[::step]).encode('hex')
                        result[label] = int(encoded, 16)
                else:
                    result[label] = None
    return result


def feed_all(image, scanners, indexes):
    # Scan the disk image and feed the scanners
    interesting = []
    for index in indexes:
        sector = sectors(image, index, 1, fill=False)
        if not sector:
            break

        for instance in scanners:
            res = instance.feed(index, sector)
            if res is not None:
                logging.info('Found {} at sector {}'.format(res, index))
                interesting.append(index)
    return interesting


def printable(text, default='.', alphabet=None):
    """Replace unprintable characters in a text with a default one."""
    if alphabet is None:
        alphabet = unicode_printable
    return ''.join((i if i in alphabet else default) for i in text)


def hexdump(stream, count=16):
    """Return a nice hexadecimal dump representation of stream."""
    stream = str(stream)
    encoded = stream.encode('hex')
    chunks = [encoded[i:i+2] for i in xrange(0, len(encoded), 2)]
    lines = (
        u'%08d: ' % i + ' '.join(chunks[i:i+count]) + ' | ' +
        printable(stream[i:i+count], alphabet=ascii_printable)
        for i in xrange(0, len(chunks), count)
    )
    return '\n'.join(lines)


def pretty(dictionary):
    """Format dictionary with the pretty printer."""
    return printer.pformat(dictionary)


def show(dictionary):
    """Print dictionary with the pretty printer."""
    printer.pprint(dictionary)


def tiny_repr(element):
    """Return a representation of unicode strings without the u."""
    rep = repr(element)
    return rep[1:] if type(element) == unicode else rep


def readable_bytes(amount):
    """Return a human readable string representing a size in bytes."""
    if amount is None:
        return '??? B'
    if amount < 1:
        return '%.2f B' % amount
    powers = {
        0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'
    }
    biggest = max(i for i in powers if amount / 1024.**i >= 1)
    scaled = amount / 1024.**biggest
    return '%.2f %sB' % (scaled, powers[biggest])


def _file_tree_repr(node):
    """Give a nice representation for the tree."""
    desc = (
        ' [GHOST]' if node.is_ghost else
        ' [DELETED]' if node.is_deleted else ''
    )
    tail = '/' if node.is_directory else ''
    data = [
        ('Id', node.index),
        ('Offset', node.offset),
        (
            'Offset bytes',
            node.offset * sector_size
            if node.offset is not None else None
        )
        # ('MAC', node.mac)
    ]
    if not node.is_directory:
        data += [('Size', readable_bytes(node.size))]
    return u'%s%s (%s) %s' % (
        node.name, tail, ', '.join(a + ': ' + str(b) for a, b in data), desc
    )


def tree_folder(directory, padding=0):
    """Return a tree-like textual representation of a directory."""
    lines = []
    pad = ' ' * padding
    lines.append(
        pad + _file_tree_repr(directory)
    )
    padding = padding + 2
    pad = ' ' * padding
    for entry in directory.children:
        if len(entry.children) or entry.is_directory:
            lines.append(tree_folder(entry, padding))
        else:
            lines.append(
                pad + _file_tree_repr(entry)
            )
    return '\n'.join(lines)


def _bodyfile_repr(node, path):
    """Return a body file line for node."""
    end = '/' if node.is_directory or len(node.children) else ''
    return '|'.join(unicode(el) for el in [
        '0',                        # MD5
        path + node.name + end,     # name
        node.index,                 # inode
        '0', '0', '0',              # mode, UID, GID
        node.size if node.size is not None else 0,
        unixtime(node.mac['access']),
        unixtime(node.mac['modification']),
        unixtime(node.mac['creation']),
        '0'
    ])


def bodyfile_folder(directory, path=''):
    """Create a body file compatible with TSK 3.x.

    Format:
    '#MD5|name|inode|mode_as_string|UID|GID|size|atime|mtime|ctime|crtime'
    See also: http://wiki.sleuthkit.org/index.php?title=Body_file"""
    lines = [_bodyfile_repr(directory, path)]
    path += directory.name + '/'
    for entry in directory.children:
        if len(entry.children) or entry.is_directory:
            lines += bodyfile_folder(entry, path)
        else:
            lines.append(_bodyfile_repr(entry, path))
    return lines


def _ltx_clean(label):
    """Small filter to prepare strings to be included in LaTeX code."""
    clean = str(label).replace('$', r'\$').replace('_', r'\_')
    if clean[0] == '-':
        clean = r'\textminus{}' + clean[1:]
    return clean


def _tikz_repr(node):
    """Represent the node for a Tikz diagram."""
    return r'node %s{%s\enskip{}%s}' % (
        '[ghost]' if node.is_ghost else '[deleted]' if node.is_deleted else '',
        _ltx_clean(node.index), _ltx_clean(node.name)
    )


def tikz_child(directory, padding=0):
    """Write a child row for Tikz representation."""
    pad = ' ' * padding
    lines = [r'%schild {%s' % (pad, _tikz_repr(directory))]
    count = len(directory.children)
    for entry in directory.children:
        content, number = tikz_child(entry, padding+4)
        lines.append(content)
        count += number
    lines.append('}')
    for entry in xrange(count):
        lines.append('child [missing] {}')
    return '\n'.join(lines).replace('\n}', '}'), count


def tikz_part(part):
    """Create LaTeX code to represent the directory structure as a nice Tikz
    diagram.

    See also: http://www.texample.net/tikz/examples/filesystem-tree/"""

    preamble = (r"""%\usepackage{tikz}
    %\usetikzlibrary{trees}""")

    begin_tree = r"""\begin{tikzpicture}[%
    grow via three points={one child at (1.75em,-1.75em) and
    two children at (1.75em,-1.75em) and (1.75em,-3.5em)},
    edge from parent path={(\tikzparentnode.south) |- (\tikzchildnode.west)}]
    \scriptsize
    """
    end_tree = r"""\end{tikzpicture}"""

    lines = [r'\node [root] {File System Structure}']
    lines += [tikz_child(entry, 4)[0] for entry in (part.root, part.lost)]
    lines.append(';')

    return '%s\n\n%s\n%s\n%s' % (
        preamble, begin_tree, '\n'.join(lines), end_tree
    )


def csv_part(part):
    """Provide a CSV representation for a partition."""
    contents = [
        ','.join(('Id', 'Parent', 'Name', 'Modification Time',
                  'Access Time', 'Creation Time', 'Size (bytes)',
                  'Size (human)', 'Offset (bytes)', 'Offset (sectors)',
                  'Directory', 'Deleted', 'Ghost'))
    ]
    for index in part.files:
        obj = part.files[index]
        contents.append(
                u'%s,%s,"%s",%s,%s,%s,%s,%s,%s,%s,%s,%s,%s' % (
                    obj.index, obj.parent, obj.name,
                    obj.mac['modification'], obj.mac['access'],
                    obj.mac['creation'], obj.size,
                    readable_bytes(obj.size),
                    (obj.offset * sector_size
                     if obj.offset is not None else None),
                    obj.offset,
                    '1' if obj.is_directory else '',
                    '1' if obj.is_deleted else '',
                    '1' if obj.is_ghost else ''
                )
        )
    return contents


def _sub_locate(text, directory, part):
    """Helper for locate."""
    lines = []
    for entry in sorted(directory.children, key=lambda node: node.name):
        path = entry.full_path(part)
        if text in path.lower():
            lines.append((entry, path))
        if len(entry.children) or entry.is_directory:
            lines += _sub_locate(text, entry, part)
    return lines


def locate(part, text):
    """Return paths of files matching the text."""
    lines = []
    text = text.lower()
    lines += _sub_locate(text, part.lost, part)
    lines += _sub_locate(text, part.root, part)
    return lines


def merge(part, piece):
    """Merge piece into part (both are partitions)."""
    for index in piece.files:
        if (
            index not in part.files or
            part.files[index].is_ghost
        ):
            part.add_file(piece.files[index])
