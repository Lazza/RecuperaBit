"""NTFS plug-in.

This plug-in contains the necessary logic to parse traces of NTFS file systems,
including MFT entries and directory indexes."""

# RecuperaBit
# Copyright 2014-2016 Andrea Lazzarotto
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
from collections import Counter

from ..utils import sectors, unpack, merge
from ..logic import approximate_matching, SparseList

from constants import sector_size, max_sectors
from core_types import File, Partition, DiskScanner

from ntfs_fmt import entry_fmt, boot_sector_fmt, indx_fmt, indx_header_fmt
from ntfs_fmt import indx_dir_entry_fmt, attr_header_fmt, attr_resident_fmt
from ntfs_fmt import attr_nonresident_fmt, attr_names, attr_types_fmt
from ntfs_fmt import attribute_list_parser

# Some attributes may appear multiple times
multiple_attributes = set([
    '$FILE_NAME',
    '$DATA',
    '$INDEX_ROOT',
    '$INDEX_ALLOCATION',
    '$BITMAP'
])

# Size of records in sectors
FILE_size = 2
INDX_size = 8


def best_name(entries):
    """Return the best file name available.

    This function accepts a list of tuples formed by a namespace and a string.
    In case of more than one choice, it returns preferrably the one in the NTFS
    namespace (code == 3)."""
    if len(entries) == 0:
        return None

    entries.sort()
    if entries[-1][0] == 3:
        name = entries[-1][1]
    else:
        name = entries[0][1]
    return name if len(name) else None


def parse_mft_attr(attr):
    """Parse the contents of a MFT attribute."""
    header = unpack(attr, attr_header_fmt)
    attr_type = header['type']

    if attr_type not in attr_names:
        return header, None

    if header['non_resident']:
        nonresident = unpack(attr, attr_nonresident_fmt)
        header.update(nonresident)
    else:
        resident = unpack(attr, attr_resident_fmt)
        header.update(resident)
        offset = header['content_off']
        content = attr[offset:]

    name = attr_names[attr_type]
    if not header['non_resident'] and name in attr_types_fmt:
        size = header['content_size']
        data = unpack(content[:size], attr_types_fmt[name])
        header['content'] = data

    return header, name


def _apply_fixup_values(header, entry):
    """Apply the fixup values to FILE and INDX records."""
    offset = header['off_fixup']
    for i in xrange(1, header['n_entries']):
        pos = sector_size * i
        entry[pos-2:pos] = entry[offset + 2*i:offset + 2*(i+1)]


def _attributes_reader(entry, offset):
    """Read every attribute."""
    attributes = {}
    while offset < len(entry) - 16:
        try:
            attr, name = parse_mft_attr(entry[offset:])
        except TypeError:
            # The attribute was broken, we need to terminate here
            return attributes
        attr['dump_offset'] = offset
        if attr['length'] == 0:
            # End of attribute list
            break
        else:
            offset = offset + attr['length']
            if name is None:
                # Skip broken/unknown attribute
                continue
            if name not in attributes:
                if name not in multiple_attributes:
                    attributes[name] = attr
                else:
                    attributes[name] = [attr]
            else:
                if name in multiple_attributes:
                    attributes[name].append(attr)
                else:
                    logging.error('Cannot handle multiple attribute %s', name)
                    raise NotImplementedError
    return attributes


def parse_file_record(entry):
    """Parse the contents of a FILE record (MFT entry)."""
    header = unpack(entry, entry_fmt)
    if (header['size_alloc'] > len(entry) or
            len(entry) < FILE_size*sector_size):
        header['valid'] = False
        return header

    # Old versions of NTFS don't have a MFT record number.
    if header['off_fixup'] < 48:
        header['record_n'] = None

    _apply_fixup_values(header, entry)

    attributes = _attributes_reader(entry, header['off_first'])
    header['valid'] = True
    header['attributes'] = attributes
    return header


def parse_indx_record(entry):
    """Parse the contents of a INDX record (directory index)."""
    header = unpack(entry, indx_fmt)

    _apply_fixup_values(header, entry)

    node_data = unpack(entry[24:], indx_header_fmt)
    node_data['off_start_list'] += 24
    node_data['off_end_list'] += 24
    node_data['off_end_buffer'] += 24
    header.update(node_data)

    offset = header['off_start_list']
    entries = []
    while offset < header['off_end_list']:
        entry_data = unpack(entry[offset:], indx_dir_entry_fmt)
        if entry_data['content_length']:
            try:
                file_name = unpack(
                    entry[offset + 16:],
                    attr_types_fmt['$FILE_NAME']
                )
            except UnicodeDecodeError:  # Invalid file name
                pass
            except TypeError:   # Invalid name length
                pass
            # Perform checks to avoid false positives
            name_ok = file_name['name'] is not None
            namespace_ok = 0 <= file_name['namespace'] <= 3
            size_ok = file_name['real_size'] <= file_name['allocated_size']
            features_ok = not (
                file_name['flags'] == 0 and
                file_name['parent_seq'] > 1024
            )
            if name_ok and namespace_ok and size_ok and features_ok:
                entry_data['file_info'] = file_name
                entries.append(entry_data)
            else:
                break
        if entry_data['entry_length']:
            offset += entry_data['entry_length']
        else:
            break
    header['entries'] = entries
    header['valid'] = len(entries) > 0
    return header


def _integrate_attribute_list(parsed, part, image):
    """Integrate missing attributes in the parsed MTF entry."""
    base_record = parsed['record_n']
    attrs = parsed['attributes']
    attr = attrs['$ATTRIBUTE_LIST']

    spc = part.sec_per_clus
    if 'runlist' in attr:
        clusters_pos = 0
        entries = []
        size = attr['real_size']
        for entry in attr['runlist']:
            clusters_pos += entry['offset']
            length = min(entry['length'] * spc * sector_size, size)
            size -= length
            real_pos = clusters_pos * spc + part.offset
            dump = sectors(image, real_pos, length, 1)
            entries += attribute_list_parser(dump)
        attr['content'] = {'entries': entries}
    else:
        entries = attr['content']['entries']

    # Divide entries by type
    types = set(e['type'] for e in entries)
    entries_by_type = {
        t: set(
            e['file_ref'] for e in entries
            if e['type'] == t and e['file_ref'] is not None
        )
        for t in types
    }
    # Remove completely "local" types or empty lists
    for num in list(entries_by_type):
        files = entries_by_type[num]
        if (
            len(files) == 0 or
            (len(files) == 1 and iter(files).next() == base_record)
        ):
            del entries_by_type[num]

    mft_pos = part.mft_pos
    for num in entries_by_type:
        # Read contents of child entries
        for index in entries_by_type[num]:
            real_pos = mft_pos + index * FILE_size
            dump = sectors(image, real_pos, FILE_size)
            child_parsed = parse_file_record(dump)
            if 'attributes' not in child_parsed:
                continue
            # Update the main entry (parsed)
            if child_parsed['base_record'] == base_record:
                child_attrs = child_parsed['attributes']
                for name in child_attrs:
                    if name in multiple_attributes:
                        try:
                            attrs[name] += child_attrs[name]
                        except KeyError:
                            attrs[name] = child_attrs[name]
                    else:
                        attrs[name] = child_attrs[name]


class NTFSFile(File):
    """NTFS File."""
    def __init__(self, parsed, offset, is_ghost=False, ads=''):
        index = parsed['record_n']
        ads_suffix = ':' + ads if ads != '' else ads
        if ads != '':
            index = unicode(index) + ads_suffix
        attrs = parsed['attributes']
        filenames = attrs['$FILE_NAME']
        datas = attrs['$DATA'] if '$DATA' in attrs else []

        size = None
        for attr in datas:
            if attr['name'] == ads:
                if 'real_size' in attr:
                    size = attr['real_size']
                elif not attr['non_resident']:
                    size = attr['content_size']
                break

        name = best_name([
            (f['content']['namespace'], f['content']['name'] + ads_suffix)
            for f in filenames if f.has_key('content') and
            f['content'] is not None and
            f['content']['name_length'] > 0 and
            f['content']['name'] is not None
        ])
        hasname = name is not None

        if not hasname:
            name = 'File_%s' % index

        is_dir = (parsed['flags'] & 0x02) > 0 and not len(ads)
        is_del = (parsed['flags'] & 0x01) == 0
        File.__init__(self, index, name, size, is_dir, is_del, is_ghost)
        # Additional attributes
        if hasname:
            parent_id = filenames[0]['content']['parent_entry']
            File.set_parent(self, parent_id)
            File.set_offset(self, offset)
            first = filenames[0]['content']
            File.set_mac(
                self, first['modification_time'],
                first['access_time'], first['creation_time']
            )
        self.ads = ads

    @staticmethod
    def _padded_bytes(image, offset, size):
        dump = sectors(image, offset, size, 1)
        if len(dump) < size:
            logging.warning(
                'Failed to read byte(s). Padding with 0x00. Offset: {} Size: '
                '{}'.format(offset, size))
            dump += bytearray('\x00' * (size - len(dump)))
        return dump

    def content_iterator(self, partition, image, datas):
        """Return an iterator for the contents of this file."""
        vcn = 0
        spc = partition.sec_per_clus
        for attr in datas:
            diff = attr['start_VCN'] - vcn
            if diff > 0:
                logging.warning(
                    u'Missing part for {}, filling {} clusters '
                    'with zeros'.format(self, diff)
                )
            while diff > 0:
                amount = min(max_sectors//spc, diff)
                vcn += amount
                diff -= amount
                yield '\x00' * sector_size * spc * amount

            clusters_pos = 0
            size = attr['real_size']

            if 'runlist' not in attr:
                logging.error(
                    u'Cannot restore {}, missing runlist'.format(self)
                )
                break

            for entry in attr['runlist']:
                length = min(entry['length'] * spc * sector_size, size)
                size -= length
                # Sparse runlist
                if entry['offset'] is None:
                    while length > 0:
                        amount = min(max_sectors*sector_size, length)
                        length -= amount
                        yield '\x00' * amount
                    continue
                # Normal runlists
                clusters_pos += entry['offset']
                real_pos = clusters_pos * spc + partition.offset
                # Avoid to fill memory with huge blocks
                offset = 0
                while length > 0:
                    amount = min(max_sectors*sector_size, length)
                    position = real_pos*sector_size + offset
                    partial = self._padded_bytes(image, position, amount)
                    length -= amount
                    offset += amount
                    yield str(partial)
            vcn = attr['end_VCN'] + 1

    def get_content(self, partition):
        """Extract the content of the file.

        This method works by extracting the $DATA attribute."""
        if self.is_ghost:
            logging.error(u'Cannot restore ghost file {}'.format(self))
            return None

        image = DiskScanner.get_image(partition.scanner)
        dump = sectors(image, File.get_offset(self), FILE_size)
        parsed = parse_file_record(dump)

        if not parsed['valid'] or 'attributes' not in parsed:
            logging.error(u'Invalid MFT entry for {}'.format(self))
            return None
        attrs = parsed['attributes']
        if ('$ATTRIBUTE_LIST' in attrs and
                partition.sec_per_clus is not None):
            _integrate_attribute_list(parsed, partition, image)
        if '$DATA' not in attrs:
            attrs['$DATA'] = []
        datas = [d for d in attrs['$DATA'] if d['name'] == self.ads]
        if not len(datas):
            if not self.is_directory:
                logging.error(u'Cannot restore $DATA attribute(s) '
                              'for {}'.format(self))
            return None

        # TODO implemented compressed attributes
        for d in datas:
            if d['flags'] & 0x01:
                logging.error(u'Cannot restore compressed $DATA attribute(s) '
                              'for {}'.format(self))
                return None
            elif d['flags'] & 0x4000:
                logging.warning(u'Found encrypted $DATA attribute(s) '
                                'for {}'.format(self))

        # Handle resident file content
        if len(datas) == 1 and not datas[0]['non_resident']:
            single = datas[0]
            start = single['dump_offset'] + single['content_off']
            end = start + single['content_size']
            content = dump[start:end]
            return str(content)
        else:
            if partition.sec_per_clus is None:
                logging.error(u'Cannot restore non-resident $DATA '
                              'attribute(s) for {}'.format(self))
                return None
            non_resident = sorted(
                (d for d in attrs['$DATA'] if d['non_resident']),
                key=lambda x: x['start_VCN']
            )
            if len(non_resident) != len(datas):
                logging.warning(
                    u'Found leftover resident $DATA attributes for '
                    '{}'.format(self)
                )
            return self.content_iterator(partition, image, non_resident)

    def ignore(self):
        """Determine which files should be ignored."""
        return (
            (self.index == '8:$Bad') or
            (self.parent == 11 and self.ads == '$J')    # $UsnJrnl
        )


class NTFSPartition(Partition):
    """Partition with additional fields for NTFS recovery."""
    def __init__(self, scanner, position=None):
        Partition.__init__(self, 'NTFS', 5, scanner)
        self.sec_per_clus = None
        self.mft_pos = position
        self.mftmirr_pos = None

    def additional_repr(self):
        """Return additional values to show in the string representation."""
        return [
            ('Sec/Clus', self.sec_per_clus),
            ('MFT offset', self.mft_pos),
            ('MFT mirror offset', self.mftmirr_pos)
        ]


class NTFSScanner(DiskScanner):
    """NTFS Disk Scanner."""
    def __init__(self, pointer):
        DiskScanner.__init__(self, pointer)
        self.found_file = set()
        self.parsed_file_review = {}
        self.found_indx = set()
        self.parsed_indx = {}
        self.indx_list = None
        self.found_boot = []
        self.found_spc = []

    def feed(self, index, sector):
        """Feed a new sector."""
        # check boot sector
        if sector.endswith('\x55\xAA') and 'NTFS' in sector[:8]:
            self.found_boot.append(index)
            return 'NTFS boot sector'

        # check file record
        if sector.startswith(('FILE', 'BAAD')):
            self.found_file.add(index)
            return 'NTFS file record'

        # check index record
        if sector.startswith('INDX'):
            self.found_indx.add(index)
            return 'NTFS index record'

    @staticmethod
    def add_indx_entries(entries, part):
        """Insert new ghost files which were not already found."""
        for rec in entries:
            if (rec['record_n'] not in part.files and
                    rec['$FILE_NAME'] is not None):
                # Compatibility with the structure of a MFT entry
                rec['attributes'] = {
                    '$FILE_NAME': [{'content': rec['$FILE_NAME']}]
                }
                """Although the structure of r is similar to that of a MFT
                entry, flags were about the index, not about the file. We
                don't know if the element is a directory or not, hence we
                mark it as a file. It can be deduced if it is a directory
                by looking at the number of children, after the
                reconstruction."""
                rec['flags'] = 0x1
                part.add_file(NTFSFile(rec, None, is_ghost=True))

    def add_from_indx_root(self, parsed, part):
        """Add ghost entries to part from INDEX_ROOT attributes in parsed."""
        for attribute in parsed['attributes']['$INDEX_ROOT']:
            if (attribute.get('content') is None or
                    attribute['content'].get('records') is None):
                continue
            self.add_indx_entries(attribute['content']['records'], part)

    def most_likely_sec_per_clus(self):
        """Determine the most likely value of sec_per_clus of each partition,
        to speed up the search."""
        counter = Counter()
        counter.update(self.found_spc)
        counter.update(2**i for i in xrange(8))
        return [i for i, _ in counter.most_common()]

    def find_boundary(self, part, mft_address, multipliers):
        """Determine the starting sector of a partition with INDX records."""
        nodes = (
            self.parsed_file_review[node.offset]
            for node in part.files.itervalues()
            if node.offset in self.parsed_file_review and
            '$INDEX_ALLOCATION' in
            self.parsed_file_review[node.offset]['attributes']
        )

        text_list = self.indx_list
        width = text_list.__len__()

        base_pattern = {}
        for parsed in nodes:
            for attr in parsed['attributes']['$INDEX_ALLOCATION']:
                clusters_pos = 0
                if 'runlist' not in attr:
                    continue
                runlist = attr['runlist']
                for entry in runlist:
                    clusters_pos += entry['offset']
                    base_pattern[clusters_pos] = parsed['record_n']
        if not len(base_pattern):
            return (None, None)

        results = []
        min_support = 2
        for sec_per_clus in multipliers:
            pattern = {
                i * sec_per_clus: base_pattern[i]
                for i in base_pattern
            }

            delta = min(pattern)
            normalized = {
                i-delta: pattern[i]
                for i in pattern if i-delta <= width
                # Avoid extremely long, useless patterns
            }
            if len(normalized) < min_support:
                continue

            pattern_list = SparseList(normalized)
            solution = approximate_matching(
                text_list, pattern_list, mft_address + delta, k=min_support
            )
            if solution is not None:
                # Avoid negative offsets and ambiguous situations
                solution[0] = [i-delta for i in solution[0] if i-delta >= 0]
                if len(solution[0]) == 1:
                    positions, amount, perc = solution
                    results.append((positions, perc, sec_per_clus))
                    # Reasonably, this is a correct match
                    if perc > 0.25 and amount > 256:
                        break
                min_support = max(min_support, solution[1])

        if len(results):
            results.sort(key=lambda r: r[1])
            positions, _, spc = results[0]
            return (positions[0], spc)
        else:
            return (None, None)

    def add_from_indx_allocation(self, parsed, part):
        """Add ghost entries to part from INDEX_ALLOCATION attributes in parsed.

        This procedure requires that the beginning of the partition has already
        been discovered."""
        read_again = set()
        for attr in parsed['attributes']['$INDEX_ALLOCATION']:
            clusters_pos = 0
            if 'runlist' not in attr:
                continue
            runlist = attr['runlist']
            for entry in runlist:
                clusters_pos += entry['offset']
                real_pos = clusters_pos * part.sec_per_clus + part.offset
                if real_pos in self.parsed_indx:
                    content = self.parsed_indx[real_pos]
                    # Check if the entry matches
                    if parsed['record_n'] == content['parent']:
                        discovered = set(
                            c for c in content['children']
                            if c not in part.files
                        )
                        # If there are new files, read the INDX again
                        if len(discovered):
                            read_again.add(real_pos)

        img = DiskScanner.get_image(self)
        for position in read_again:
            dump = sectors(img, position, INDX_size)
            entries = parse_indx_record(dump)['entries']
            self.add_indx_entries(entries, part)

    def add_from_attribute_list(self, parsed, part, offset):
        """Add additional entries to part from attributes in ATTRIBUTE_LIST.

        Files with many attributes may have additional attributes not in the
        MFT entry. When this happens, it is necessary to find the other
        attributes. They may contain additional information, such as $DATA
        attributes for ADS. This procedure requires that the beginning of the
        partition has already been discovered."""
        image = DiskScanner.get_image(self)
        _integrate_attribute_list(parsed, part, image)

        attrs = parsed['attributes']
        if '$DATA' in attrs:
            for attribute in attrs['$DATA']:
                ads_name = attribute['name']
                if len(ads_name):
                    part.add_file(NTFSFile(parsed, offset, ads=ads_name))

    def add_from_mft_mirror(self, part):
        """Fix the first file records using the MFT mirror."""
        img = DiskScanner.get_image(self)
        mirrpos = part.mftmirr_pos
        if mirrpos is None:
            return

        for i in xrange(4):
            node = part.get(i)
            if node is None or node.is_ghost:
                position = mirrpos + i * FILE_size
                dump = sectors(img, position, FILE_size)
                parsed = parse_file_record(dump)
                if parsed['valid'] and '$FILE_NAME' in parsed['attributes']:
                    node = NTFSFile(parsed, position)
                    part.add_file(node)
                    logging.info(
                        u'Repaired MFT entry #%s - %s in partition at offset '
                        '%s from backup', node.index, node.name, part.offset
                    )

    def finalize_reconstruction(self, part):
        """Finish information gathering from a file.

        This procedure requires that the beginning of the
        partition has already been discovered."""
        logging.info('Adding extra attributes from $ATTRIBUTE_LIST')
        # Select elements with many attributes
        many_attributes_it = (
            node for node in list(part.files.itervalues())
            if node.offset in self.parsed_file_review and
            '$ATTRIBUTE_LIST' in
            self.parsed_file_review[node.offset]['attributes']
        )
        for node in many_attributes_it:
            parsed = self.parsed_file_review[node.offset]
            self.add_from_attribute_list(parsed, part, node.offset)

        logging.info('Adding ghost entries from $INDEX_ALLOCATION')
        # Select only elements with $INDEX_ALLOCATION
        allocation_it = (
            node for node in list(part.files.itervalues())
            if node.offset in self.parsed_file_review and
            '$INDEX_ALLOCATION' in
            self.parsed_file_review[node.offset]['attributes']
        )
        for node in allocation_it:
            parsed = self.parsed_file_review[node.offset]
            self.add_from_indx_allocation(parsed, part)

    def get_partitions(self):
        """Get a list of the found partitions."""
        partitioned_files = {}
        img = DiskScanner.get_image(self)

        logging.info('Parsing MFT entries')
        for position in self.found_file:
            dump = sectors(img, position, FILE_size)
            try:
                parsed = parse_file_record(dump)
            except NotImplementedError:
                logging.error(
                    'Problem parsing record on sector %d', position
                )
                continue
            attrs = parsed['attributes'] if 'attributes' in parsed else {}
            if not parsed['valid'] or '$FILE_NAME' not in attrs:
                continue

            # Partition files based on corresponding entry 0
            if parsed['record_n'] is not None:
                offset = position - parsed['record_n'] * FILE_size
                try:
                    part = partitioned_files[offset]
                except KeyError:
                    partitioned_files[offset] = NTFSPartition(self, offset)
                    part = partitioned_files[offset]
                attributes = parsed['attributes']
                if '$DATA' in attributes:
                    for attribute in attributes['$DATA']:
                        ads_name = attribute['name']
                        part.add_file(NTFSFile(parsed, position, ads=ads_name))
                """Add the file again, just in case the $DATA attributes are
                missing."""
                part.add_file(NTFSFile(parsed, position))

                # Handle information deduced from INDX records
                if '$INDEX_ROOT' in attrs:
                    self.add_from_indx_root(parsed, part)
                # Save for later use
                if '$INDEX_ALLOCATION' in attrs or '$ATTRIBUTE_LIST' in attrs:
                    self.parsed_file_review[position] = parsed
            # TODO [Future] handle files for which there is no record_number

        # Parse INDX records
        logging.info('Parsing INDX records')
        for position in self.found_indx:
            dump = sectors(img, position, INDX_size)
            parsed = parse_indx_record(dump)
            if not parsed['valid']:
                continue

            entries = parsed['entries']
            referred = (el['file_info']['parent_entry'] for el in entries)
            record_n = Counter(referred).most_common(1)[0][0]
            # Save references for future access
            self.parsed_indx[position] = {
                'parent': record_n,
                'children': set(el['record_n'] for el in entries)
            }

        indx_info = self.parsed_indx
        self.indx_list = SparseList({
            pos: indx_info[pos]['parent'] for pos in indx_info
        })

        # Extract boot record information
        logging.info('Reading boot sectors')
        for index in self.found_boot:
            dump = sectors(img, index, 1)
            parsed = unpack(dump, boot_sector_fmt)
            sec_per_clus = parsed['sectors_per_cluster']
            self.found_spc.append(sec_per_clus)
            relative = parsed['MFT_addr'] * sec_per_clus
            mirr_relative = parsed['MFTmirr_addr'] * sec_per_clus
            part = None
            # Look for matching partition, either as boot sector or backup
            for delta in (0, parsed['sectors']):
                index = index - delta
                address = relative + index
                # Set partition as recoverable
                if address in partitioned_files:
                    part = partitioned_files[address]
                    part.set_recoverable(True)
                    part.set_size(parsed['sectors'])
                    part.offset = index
                    part.sec_per_clus = sec_per_clus
                    part.mftmirr_pos = mirr_relative + index
                    break

        # Repair MFT if the mirror is available
        for address in list(partitioned_files):
            # This could have been deleted in a previous iteration
            if address not in partitioned_files:
                continue
            part = partitioned_files[address]
            mirrpos = part.mftmirr_pos
            if mirrpos is None:
                entry = part.get(1)     # $MFTMirr
                if entry is None:
                    continue
                else:
                    # Infer MFT mirror position
                    dump = sectors(img, entry.offset, FILE_size)
                    mirror = parse_file_record(dump)
                    if (mirror['valid'] and 'attributes' in mirror and
                            '$DATA' in mirror['attributes']):
                        datas = mirror['attributes']['$DATA']
                        if (len(datas) == 1 and datas[0]['non_resident'] and
                                'runlist' in datas[0] and
                                len(datas[0]['runlist']) > 0 and
                                'offset' in datas[0]['runlist'][0]):
                            relative = datas[0]['runlist'][0]['offset']
                            spc = part.sec_per_clus
                            if spc is None:
                                continue
                            mirrpos = relative * spc + part.offset
                            part.mftmirr_pos = mirrpos

            self.add_from_mft_mirror(part)

            # Remove bogus partitions generated by MFT mirrors
            if mirrpos in partitioned_files:
                bogus = partitioned_files[mirrpos]
                # Check if it looks like a MFT mirror
                if len(bogus.files) == 4 and max(bogus.files) < 4:
                    logging.debug(
                        'Dropping bogus NTFS partition with MFT '
                        'position %d generated by MFT mirror of '
                        'partition at offset %d',
                        bogus.mft_pos, part.offset
                    )
                    partitioned_files.pop(mirrpos)

        # Acquire additional information from $INDEX_ALLOCATION
        logging.info('Finding partition geometry')
        most_likely = self.most_likely_sec_per_clus()
        for address in partitioned_files:
            part = partitioned_files[address]
            if part.offset is None:
                # Find geometry by approximate string matching
                offset, sec_per_clus = self.find_boundary(
                    part, address, most_likely
                )
                if offset is not None:
                    part.set_recoverable(True)
                    part.offset = offset
                    part.sec_per_clus = sec_per_clus
            else:
                offset, sec_per_clus = part.offset, part.sec_per_clus
            if offset is not None:
                logging.info(
                    'Finalizing MFT reconstruction of partition at offset %i',
                    offset
                )
                self.finalize_reconstruction(part)

        # Merge pieces from fragmented MFT
        for address in list(partitioned_files):
            # This could have been deleted in a previous iteration
            if address not in partitioned_files:
                continue
            part = partitioned_files[address]
            entry = part.get(0)     # $MFT
            if entry is None or part.sec_per_clus is None:
                continue
            dump = sectors(img, entry.offset, FILE_size)
            parsed = parse_file_record(dump)
            if not parsed['valid'] or 'attributes' not in parsed:
                continue

            if '$ATTRIBUTE_LIST' in parsed['attributes']:
                _integrate_attribute_list(parsed, part, img)
            attrs = parsed['attributes']
            if '$DATA' not in attrs or len(attrs['$DATA']) < 1:
                continue

            if 'runlist' not in attrs['$DATA'][0]:
                continue
            runlist = attrs['$DATA'][0]['runlist']
            if len(runlist) > 1:
                logging.info(
                    'MFT for partition at offset %d is fragmented. Trying to '
                    'merge %d parts...', part.offset, len(runlist)
                )
                clusters_pos = runlist[0]['offset']
                spc = part.sec_per_clus
                size = runlist[0]['length']
                for entry in runlist[1:]:
                    clusters_pos += entry['offset']
                    real_pos = clusters_pos * part.sec_per_clus + part.offset
                    position = real_pos - size*spc
                    if position in partitioned_files:
                        piece = partitioned_files[position]
                        if piece.offset is None or piece.offset == part.offset:
                            conflicts = [
                                i for i in piece.files if
                                not piece.files[i].is_ghost and
                                i in part.files and
                                not part.files[i].is_ghost
                            ]
                            if not len(conflicts):
                                logging.debug(
                                    'Merging partition with MFT offset %d into'
                                    ' %s (fragmented MFT)', piece.mft_pos, part
                                )
                                # Merge the partitions
                                merge(part, piece)
                                # Remove the fragment
                                partitioned_files.pop(position)
                            else:
                                logging.debug(
                                    'NOT merging partition with MFT offset %d into'
                                    ' %s (possible fragmented MFT) due to conflicts', piece.mft_pos, part
                                )
                    size += entry['length']

        return partitioned_files
