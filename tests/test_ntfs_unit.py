"""Unit tests for NTFS parsing functions and core types."""

import unittest
from unittest.mock import Mock

# Import the modules under test
from recuperabit.fs.ntfs import (
    NTFSFile, NTFSPartition, 
    NTFSScanner, best_name, _apply_fixup_values
)
from recuperabit.logic import SparseList


class TestNTFSParsing(unittest.TestCase):
    """Test NTFS parsing functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a mock MFT entry for testing
        self.mock_mft_entry = bytearray(1024)  # 1KB MFT entry
        # FILE signature
        self.mock_mft_entry[0:4] = b'FILE'
        # Fixup offset at position 4-6 (little endian)
        self.mock_mft_entry[4:6] = (48).to_bytes(2, 'little')
        # Number of fixup entries at position 6-8
        self.mock_mft_entry[6:8] = (2).to_bytes(2, 'little')
        # First attribute offset at position 20-22
        self.mock_mft_entry[20:22] = (56).to_bytes(2, 'little')
        # MFT record size allocated at position 28-32
        self.mock_mft_entry[28:32] = (1024).to_bytes(4, 'little')
        # Record number at position 44-48
        self.mock_mft_entry[44:48] = (42).to_bytes(4, 'little')
        
        # Mock INDX entry
        self.mock_indx_entry = bytearray(4096)  # 4KB INDX entry
        # INDX signature
        self.mock_indx_entry[0:4] = b'INDX'
        # Fixup offset at position 4-6
        self.mock_indx_entry[4:6] = (40).to_bytes(2, 'little')
        # Number of fixup entries at position 6-8
        self.mock_indx_entry[6:8] = (8).to_bytes(2, 'little')
        
    def test_apply_fixup_values(self):
        """Test the fixup values application."""
        # Create a test entry with 3 sectors (1536 bytes) to test both fixups
        entry = bytearray(1536)
        header = {
            'off_fixup': 48,
            'n_entries': 3  # 1 original + 2 fixup entries
        }
        
        # Set up fixup array at offset 48
        entry[48:50] = b'\xAA\xBB'  # Original value (not used in replacement)
        entry[50:52] = b'\xCC\xDD'  # First replacement (for sector 1)
        entry[52:54] = b'\xEE\xFF'  # Second replacement (for sector 2)
        
        # Set sectors to have the original values that need fixing
        # sector_size = 512, so positions are 512*i - 2
        entry[510:512] = b'\x00\x00'  # End of first sector (512*1 - 2)
        entry[1022:1024] = b'\x00\x00'  # End of second sector (512*2 - 2)
        
        _apply_fixup_values(header, entry)
        
        # Check that fixup was applied correctly
        self.assertEqual(entry[510:512], b'\xCC\xDD')
        self.assertEqual(entry[1022:1024], b'\xEE\xFF')
        
    def test_best_name(self):
        """Test the best_name function."""
        # Test with NTFS namespace (preferred)
        entries = [(1, 'short.txt'), (3, 'long_filename.txt')]
        self.assertEqual(best_name(entries), 'long_filename.txt')
        
        # Test without NTFS namespace
        entries = [(1, 'short.txt'), (2, 'dos_name.txt')]
        self.assertEqual(best_name(entries), 'short.txt')
        
        # Test with empty list
        self.assertIsNone(best_name([]))
        
        # Test with empty name
        entries = [(3, '')]
        self.assertIsNone(best_name(entries))


class TestNTFSFile(unittest.TestCase):
    """Test NTFSFile class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_parsed = {
            'record_n': 42,
            'flags': 0x01,  # Not deleted
            'attributes': {
                '$FILE_NAME': [{
                    'content': {
                        'namespace': 3,
                        'name': 'test_file.txt',
                        'name_length': 13,
                        'parent_entry': 5
                    }
                }],
                '$DATA': [{
                    'name': '',
                    'real_size': 1024,
                    'non_resident': False,
                    'content_size': 1024
                }],
                '$STANDARD_INFORMATION': {
                    'content': {
                        'modification_time': 132000000000000000,
                        'access_time': 132000000000000000,
                        'creation_time': 132000000000000000
                    }
                }
            }
        }
        
    def test_ntfs_file_creation(self):
        """Test NTFSFile creation with valid data."""
        file_obj = NTFSFile(self.mock_parsed, 12345)
        
        self.assertEqual(file_obj.index, 42)
        self.assertEqual(file_obj.name, 'test_file.txt')
        self.assertEqual(file_obj.size, 1024)
        self.assertFalse(file_obj.is_directory)
        self.assertFalse(file_obj.is_deleted)
        self.assertFalse(file_obj.is_ghost)
        self.assertEqual(file_obj.parent, 5)
        self.assertEqual(file_obj.ads, '')
        
    def test_ntfs_file_with_ads(self):
        """Test NTFSFile creation with alternate data stream."""
        file_obj = NTFSFile(self.mock_parsed, 12345, ads='stream1')
        
        self.assertEqual(file_obj.index, '42:stream1')
        self.assertEqual(file_obj.name, 'test_file.txt:stream1')
        self.assertEqual(file_obj.ads, 'stream1')
        
    def test_ntfs_file_directory(self):
        """Test NTFSFile creation for directory."""
        self.mock_parsed['flags'] = 0x03  # Directory flag
        file_obj = NTFSFile(self.mock_parsed, 12345)
        
        self.assertTrue(file_obj.is_directory)
        
    def test_ntfs_file_deleted(self):
        """Test NTFSFile creation for deleted file."""
        self.mock_parsed['flags'] = 0x00  # Deleted flag
        file_obj = NTFSFile(self.mock_parsed, 12345)
        
        self.assertTrue(file_obj.is_deleted)
        
    def test_ntfs_file_ghost(self):
        """Test NTFSFile creation for ghost file."""
        file_obj = NTFSFile(self.mock_parsed, 12345, is_ghost=True)
        
        self.assertTrue(file_obj.is_ghost)
        
    def test_ntfs_file_ignore(self):
        """Test NTFSFile ignore logic."""
        # Test $Bad file
        self.mock_parsed['record_n'] = 8
        file_obj = NTFSFile(self.mock_parsed, 12345, ads='$Bad')
        file_obj.index = '8:$Bad'
        self.assertTrue(file_obj.ignore())
        
        # Test $UsnJrnl file
        self.mock_parsed['record_n'] = 100
        file_obj = NTFSFile(self.mock_parsed, 12345, ads='$J')
        file_obj.parent = 11
        self.assertTrue(file_obj.ignore())


class TestNTFSPartition(unittest.TestCase):
    """Test NTFSPartition class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.scanner = Mock(spec=NTFSScanner)
        
    def test_ntfs_partition_creation(self):
        """Test NTFSPartition creation."""
        partition = NTFSPartition(self.scanner, 12345)
        
        self.assertEqual(partition.fs_type, 'NTFS')
        self.assertEqual(partition.root_id, 5)
        self.assertEqual(partition.mft_pos, 12345)
        self.assertIsNone(partition.sec_per_clus)
        self.assertIsNone(partition.mftmirr_pos)
        
    def test_ntfs_partition_additional_repr(self):
        """Test NTFSPartition additional representation."""
        partition = NTFSPartition(self.scanner, 12345)
        partition.sec_per_clus = 8
        partition.mftmirr_pos = 67890
        
        additional = partition.additional_repr()
        expected = [
            ('Sec/Clus', 8),
            ('MFT offset', 12345),
            ('MFT mirror offset', 67890)
        ]
        self.assertEqual(additional, expected)


class TestNTFSScanner(unittest.TestCase):
    """Test NTFSScanner class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.scanner = NTFSScanner(Mock())
        
    def test_feed_boot_sector(self):
        """Test feeding a boot sector."""
        boot_sector = b'NTFS' + b'\x00' * 506 + b'\x55\xAA'
        result = self.scanner.feed(0, boot_sector)
        
        self.assertEqual(result, 'NTFS boot sector')
        self.assertIn(0, self.scanner.found_boot)
        
    def test_feed_file_record(self):
        """Test feeding a FILE record."""
        file_record = b'FILE' + b'\x00' * 508
        result = self.scanner.feed(100, file_record)
        
        self.assertEqual(result, 'NTFS file record')
        self.assertIn(100, self.scanner.found_file)
        
    def test_feed_baad_record(self):
        """Test feeding a BAAD record."""
        baad_record = b'BAAD' + b'\x00' * 508
        result = self.scanner.feed(200, baad_record)
        
        self.assertEqual(result, 'NTFS file record')
        self.assertIn(200, self.scanner.found_file)
        
    def test_feed_indx_record(self):
        """Test feeding an INDX record."""
        indx_record = b'INDX' + b'\x00' * 508
        result = self.scanner.feed(300, indx_record)
        
        self.assertEqual(result, 'NTFS index record')
        self.assertIn(300, self.scanner.found_indx)
        
    def test_feed_unknown_sector(self):
        """Test feeding an unknown sector."""
        unknown_sector = b'UNKN' + b'\x00' * 508
        result = self.scanner.feed(400, unknown_sector)
        
        self.assertIsNone(result)
        self.assertNotIn(400, self.scanner.found_boot)
        self.assertNotIn(400, self.scanner.found_file)
        self.assertNotIn(400, self.scanner.found_indx)
        
    def test_most_likely_sec_per_clus(self):
        """Test most_likely_sec_per_clus function."""
        self.scanner.found_spc = [8, 8, 8, 4, 4, 16]
        result = self.scanner.most_likely_sec_per_clus()
        
        # Should return 8 first (most common), then others
        self.assertEqual(result[0], 8)
        self.assertIn(4, result)
        self.assertIn(16, result)

class TestSparseList(unittest.TestCase):
    """Test SparseList functionality."""
    
    def test_sparse_list_creation(self):
        """Test SparseList creation and basic operations."""
        data = {10: 'ten', 20: 'twenty', 30: 'thirty'}
        sparse_list = SparseList(data)
        
        self.assertEqual(len(sparse_list), 31)  # 0 to 30
        self.assertEqual(sparse_list[10], 'ten')
        self.assertEqual(sparse_list[20], 'twenty')
        self.assertEqual(sparse_list[30], 'thirty')
        self.assertIsNone(sparse_list[15])  # Gap
        
    def test_sparse_list_iteration(self):
        """Test SparseList iteration."""
        data = {1: 'one', 3: 'three', 5: 'five'}
        sparse_list = SparseList(data)
        
        # SparseList should iterate over keys, not all values
        keys = list(sparse_list)
        expected_keys = [1, 3, 5]
        self.assertEqual(keys, expected_keys)
        
        # Test itervalues method for getting values
        values = list(sparse_list.itervalues())
        expected_values = ['one', 'three', 'five']
        self.assertEqual(values, expected_values)


if __name__ == '__main__':
    unittest.main()
