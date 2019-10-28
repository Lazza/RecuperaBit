"""NTFS format descriptors."""

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


from datetime import datetime

from ..utils import printable, unpack


def printable_name(name):
    """Return a printable name decoded in UTF-16."""
    decoded = []
    parts = (name[i:i+2] for i in xrange(0, len(name), 2))
    for part in parts:
        try:
            decoded.append(part.decode('utf-16'))
        except UnicodeDecodeError:
            decoded.append('\x00')
    joined = ''.join(decoded)
    # basic check for false positives
    if '\x00\x00\x00' in joined:
        return None
    return printable(joined, '#')


def windows_time(timestamp):
    """Convert a date-time value from Microsoft filetime to UTC."""
    try:
        encoded = str(timestamp[::-1]).encode('hex')
        value = int(encoded, 16)  # 'i' in unpack
        converted = datetime.utcfromtimestamp(value/10.**7 - 11644473600)
        return converted
    except ValueError:
        return None


def index_entries(dump):
    """Interpret the entries of an index."""
    offset = 0
    entries = []
    while offset < len(dump):
        parsed = unpack(dump[offset:], indx_dir_entry_fmt)
        filename = parsed['$FILE_NAME']
        entry_length = parsed['entry_length']
        valid_length = entry_length > 0
        has_name = 'name' in filename
        valid_name = has_name and len(filename['name']) > 0
        if valid_length and valid_name:
            if parsed['content_length']:
                entries.append(parsed)
            offset += entry_length
        else:
            break
        # Last entry
        if parsed['flags'] & 0x2:
            break
        # TODO handle carving of remnant entries in slack space
    return entries


def index_root_parser(dump):
    """Parse the entries contained in a $INDEX_ROOT attribute."""
    header = unpack(dump, indx_header_fmt)
    offset = header['off_start_list']
    entries = index_entries(dump[offset:])
    return entries


def runlist_unpack(runlist):
    """Parse an attribute runlist."""
    pieces = []
    while len(runlist) and runlist[0] != 0:
        off_bytes, len_bytes = divmod(runlist[0], 2**4)
        end = len_bytes + off_bytes
        decoded = unpack(runlist, [
            ('length', ('i', 1, len_bytes)),
            ('offset', ('+i', len_bytes + 1, end))
        ])
        if decoded['length'] is None or decoded['offset'] is None:
            break
        pieces.append(decoded)
        runlist = runlist[end+1:]
    return pieces


def attribute_list_parser(dump):
    """Parse entries contained in a $ATTRIBUTE_LIST attribute."""
    content = []
    while len(dump):
        decoded = unpack(dump, [
            ('type', ('i', 0, 3)),
            ('length', ('i', 4, 5)),
            ('name_length', ('i', 6, 6)),
            ('name_off', ('i', 7, 7)),
            ('start_VCN', ('i', 8, 15)),
            ('file_ref', ('i', 16, 19)),
            ('id', ('i', 24, 24))
        ])
        length = decoded['length']
        # Check either if the length is 0 or if it is None
        if not length:
            break
        content.append(decoded)
        dump = dump[length:]
    return content


def try_filename(dump):
    """Try to parse a $FILE_NAME attribute."""
    try:
        unpack(dump, attr_types_fmt['$FILE_NAME'])
    except TypeError:   # Broken attribute
        return {}

entry_fmt = [
    ('signature', ('s', 0, 3)),
    ('off_fixup', ('i', 4, 5)),
    ('n_entries', ('i', 6, 7)),
    ('LSN', ('i', 8, 15)),
    ('seq_val', ('i', 16, 17)),
    ('link_count', ('i', 18, 19)),
    ('off_first', ('i', 20, 21)),
    ('flags', ('i', 22, 23)),
    ('size_used', ('i', 24, 27)),
    ('size_alloc', ('i', 28, 31)),
    ('base_record', ('i', 32, 35)),
    ('record_n', ('i', 44, 47))   # Available only for NTFS >= 3.1
]

boot_sector_fmt = [
    ('OEM_name', ('s', 3, 10)),
    ('bytes_per_sector', ('i', 11, 12)),
    ('sectors_per_cluster', ('i', 13, 13)),
    ('sectors', ('i', 40, 47)),
    ('MFT_addr', ('i', 48, 55)),
    ('MFTmirr_addr', ('i', 56, 63)),
    ('MFT_entry_size', ('i', 64, 64)),
    ('idx_size', ('i', 68, 68)),
    ('signature', ('s', 510, 511))
]

indx_fmt = [
    ('signature', ('s', 0, 3)),
    ('off_fixup', ('i', 4, 5)),
    ('n_entries', ('i', 6, 7)),
    ('LSN', ('i', 8, 15)),
    ('seq_val', ('i', 16, 17))
]

indx_header_fmt = [
    ('off_start_list', ('i', 0, 3)),
    ('off_end_list', ('i', 4, 7)),
    ('off_end_buffer', ('i', 8, 11)),
    ('flags', ('i', 12, 15))
]

indx_dir_entry_fmt = [
    ('record_n', ('i', 0, 3)),
    ('entry_length', ('i', 8, 9)),
    ('content_length', ('i', 10, 11)),
    ('flags', ('i', 12, 15)),
    ('$FILE_NAME', (
        try_filename, 16, lambda r: 15 + (
            r['content_length'] if r['content_length'] is not None else 0
        )
    ))
    # The following is not very useful so it's not worth computing
    # 'VCN_child', (
    #     lambda s: int(str(s[::-1]).encode('hex'),16) if len(s) else None,
    #     lambda r: r['entry_length'] - (8 if r['flags'] & 0x1 else 0),
    #     lambda r: r['entry_length']
    # )
]

attr_header_fmt = [
    ('type', ('i', 0, 3)),
    ('length', ('i', 4, 7)),
    ('non_resident', ('i', 8, 8)),
    ('name_length', ('i', 9, 9)),
    ('name_off', ('i', 10, 11)),
    ('flags', ('i', 12, 13)),
    ('id', ('i', 14, 15)),
    ('name', (
        printable_name,
        lambda r: r['name_off'],
        lambda r: r['name_off'] + r['name_length']*2 - 1
    ))
]

attr_resident_fmt = [
    ('content_size', ('i', 16, 19)),
    ('content_off', ('i', 20, 21))
]

attr_nonresident_fmt = [
    ('start_VCN', ('i', 16, 23)),
    ('end_VCN', ('i', 24, 31)),
    ('runlist_offset', ('i', 32, 33)),
    ('compression_unit', ('i', 34, 35)),
    ('allocated_size', ('i', 40, 47)),
    ('real_size', ('i', 48, 55)),
    ('initialized_size', ('i', 56, 63)),
    ('runlist', (
        runlist_unpack,
        lambda r: r['runlist_offset'],
        lambda r: r['allocated_size']
    ))
]

attr_names = {
    16: '$STANDARD_INFORMATION',
    32: '$ATTRIBUTE_LIST',
    48: '$FILE_NAME',
    80: '$SECURITY_DESCRIPTOR',
    96: '$VOLUME_NAME',
    112: '$VOLUME_INFORMATION',
    128: '$DATA',
    144: '$INDEX_ROOT',
    160: '$INDEX_ALLOCATION',
    176: '$BITMAP'
}

# This structure extracts only interesting attributes.
attr_types_fmt = {
    '$STANDARD_INFORMATION': [
        ('creation_time', (windows_time, 0, 7)),
        ('modification_time', (windows_time, 8, 15)),
        ('MFT_modification_time', (windows_time, 16, 23)),
        ('access_time', (windows_time, 24, 31)),
        ('flags', ('i', 32, 35))
    ],
    '$ATTRIBUTE_LIST': [
        ('entries', (attribute_list_parser, 0, 1024))
    ],
    '$FILE_NAME': [
        ('parent_entry', ('i', 0, 5)),
        ('parent_seq', ('i', 6, 7)),
        ('creation_time', (windows_time, 8, 15)),
        ('modification_time', (windows_time, 16, 23)),
        ('MFT_modification_time', (windows_time, 24, 31)),
        ('access_time', (windows_time, 32, 39)),
        ('allocated_size', ('i', 40, 47)),
        ('real_size', ('i', 48, 55)),
        ('flags', ('i', 56, 59)),
        ('name_length', ('i', 64, 64)),
        ('namespace', ('i', 65, 65)),
        ('name', (printable_name, 66, lambda r: r['name_length']*2 + 65))
    ],
    '$INDEX_ROOT': [
        ('attr_type', ('i', 0, 3)),
        ('sorting_rule', ('i', 4, 7)),
        ('record_bytes', ('i', 8, 11)),
        ('record_clusters', ('i', 12, 12)),
        ('records', (index_root_parser, 16, lambda r: r['record_bytes']))
    ]
}
