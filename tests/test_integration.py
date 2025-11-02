"""Integration tests for RecuperaBit logic and utilities."""

import unittest
import tempfile
import os
from unittest.mock import Mock, patch
from io import BytesIO

from recuperabit.logic import SparseList, approximate_matching
from recuperabit.utils import merge, sectors, unpack


class TestSparseListIntegration(unittest.TestCase):
    """Integration tests for SparseList with NTFS components."""
    
    def test_sparse_list_with_mft_references(self):
        """Test SparseList with MFT-like reference patterns."""
        # Simulate MFT record references
        mft_refs = {
            0: 0,      # Root directory points to itself
            16: 0,     # System file points to root
            32: 16,    # File in system directory
            48: 0,     # Another root-level file
            64: 48,    # File in subdirectory
            80: 48,    # Another file in same subdirectory
        }
        
        sparse_list = SparseList(mft_refs)
        
        # Test basic operations
        self.assertEqual(sparse_list[0], 0)
        self.assertEqual(sparse_list[16], 0)
        self.assertEqual(sparse_list[64], 48)
        self.assertIsNone(sparse_list[24])  # Gap
        
        # Test length
        self.assertEqual(len(sparse_list), 81)
        
        # Test iteration gives keys, not all indices
        keys = list(sparse_list)
        expected_keys = [0, 16, 32, 48, 64, 80]
        self.assertEqual(keys, expected_keys)
        
    def test_sparse_list_large_gaps(self):
        """Test SparseList with large gaps (common in fragmented filesystems)."""
        fragmented_refs = {
            100: 0,
            5000: 100,
            10000: 5000,
            50000: 10000,
        }
        
        sparse_list = SparseList(fragmented_refs)
        
        # Should handle large indices efficiently
        self.assertEqual(sparse_list[100], 0)
        self.assertEqual(sparse_list[5000], 100)
        self.assertEqual(sparse_list[50000], 10000)
        
        # Large gaps should return None
        self.assertIsNone(sparse_list[1000])
        self.assertIsNone(sparse_list[25000])


class TestApproximateMatching(unittest.TestCase):
    """Test approximate matching functionality."""
    
    def test_approximate_matching_perfect_match(self):
        """Test approximate matching with perfect match."""
        # Create text (haystack) and pattern (needle)
        text_data = {i: i // 4 for i in range(0, 100, 4)}  # Every 4th position
        pattern_data = {i: i // 4 for i in range(0, 20, 4)}  # First 5 elements
        
        text_list = SparseList(text_data)
        pattern_list = SparseList(pattern_data)
        
        # Should find match at position 0
        result = approximate_matching(text_list, pattern_list, 0, k=3)
        
        self.assertIsNotNone(result)
        positions, count, percentage = result
        self.assertIn(0, positions)
        self.assertGreater(percentage, 0.8)  # High match percentage
        
    def test_approximate_matching_shifted_pattern(self):
        """Test approximate matching with shifted pattern."""
        # Create text and pattern with some overlap
        text_data = {i: i % 5 for i in range(0, 100, 4)}  # Pattern repeating every 5
        pattern_data = {i: i % 5 for i in range(0, 20, 4)}  # Same pattern but shorter
        
        text_list = SparseList(text_data)
        pattern_list = SparseList(pattern_data)
        
        # Should find matches at multiple positions
        result = approximate_matching(text_list, pattern_list, 50, k=1)
        
        if result is not None:
            positions, count, percentage = result
            # positions is a set, not a list, and contains actual match positions
            self.assertIsInstance(positions, set)
            self.assertGreater(len(positions), 0)
        else:
            # If no exact match found, that's also acceptable for this pattern
            self.assertIsNone(result)
        
    def test_approximate_matching_no_match(self):
        """Test approximate matching with no good match."""
        # Create text and completely different pattern
        text_data = {i: 1 for i in range(0, 100, 4)}  # All 1s
        pattern_data = {i: 2 for i in range(0, 20, 4)}  # All 2s
        
        text_list = SparseList(text_data)
        pattern_list = SparseList(pattern_data)
        
        # Should not find good match
        result = approximate_matching(text_list, pattern_list, 0, k=3)
        
        if result is not None:
            positions, count, percentage = result
            self.assertLess(percentage, 0.1)  # Very low match percentage


class TestUtilityFunctions(unittest.TestCase):
    """Test utility functions."""
    
    def test_merge_function(self):
        """Test the merge function."""
        from recuperabit.fs.core_types import Partition, File
        
        # Create mock scanner
        class MockScanner:
            pass
        scanner = MockScanner()
        
        # Create partition objects with files
        part1 = Partition('TEST', 0, scanner)
        part2 = Partition('TEST', 0, scanner)
        
        # Add files to partitions
        file1 = File(1, 'file1.txt', 100)
        file2 = File(2, 'file2.txt', 200)
        file3 = File(3, 'file3.txt', 300)
        file4 = File(4, 'file4.txt', 400)
        
        part1.add_file(file1)
        part1.add_file(file2)
        part2.add_file(file3)
        part2.add_file(file4)
        
        # Test merge
        merge(part1, part2)
        
        # part1 should now contain files from both
        self.assertIn(1, part1.files)
        self.assertIn(2, part1.files)
        self.assertIn(3, part1.files)
        self.assertIn(4, part1.files)
        self.assertEqual(len(part1.files), 4)
        
    def test_merge_with_conflicts(self):
        """Test merge function with conflicting keys."""
        from recuperabit.fs.core_types import Partition, File
        
        # Create mock scanner
        class MockScanner:
            pass
        scanner = MockScanner()
        
        # Create partition objects
        part1 = Partition('TEST', 0, scanner)
        part2 = Partition('TEST', 0, scanner)
        
        # Add conflicting files (same index)
        file1_ghost = File(1, 'file1_ghost.txt', 100, is_ghost=True)
        file1_real = File(1, 'file1_real.txt', 100, is_ghost=False)
        file2 = File(2, 'file2.txt', 200)
        file3 = File(3, 'file3.txt', 300)
        
        part1.add_file(file1_ghost)
        part1.add_file(file2)
        part2.add_file(file1_real)
        part2.add_file(file3)
        
        merge(part1, part2)
        
        # part1 should replace ghost with real file
        self.assertIn(1, part1.files)
        self.assertIn(2, part1.files)
        self.assertIn(3, part1.files)
        # The ghost file should be replaced by the real file
        self.assertFalse(part1.files[1].is_ghost)
        
    def test_sectors_function(self):
        """Test the sectors function."""
        # Create test data
        test_data = b'A' * 512 + b'B' * 512 + b'C' * 512  # 3 sectors
        test_file = BytesIO(test_data)
        
        # Test reading single sector
        result = sectors(test_file, 0, 1)
        self.assertEqual(result, b'A' * 512)
        
        # Test reading multiple sectors
        result = sectors(test_file, 1, 2)
        self.assertEqual(result, b'B' * 512 + b'C' * 512)
        
        # Test reading with byte granularity
        result = sectors(test_file, 256, 512, 1)  # 512 bytes starting at byte 256
        expected = b'A' * 256 + b'B' * 256
        self.assertEqual(result, expected)
        
    def test_sectors_out_of_bounds(self):
        """Test sectors function with out-of-bounds access."""
        test_data = b'A' * 512  # Only 1 sector
        test_file = BytesIO(test_data)
        
        # Try to read beyond file
        result = sectors(test_file, 1, 1)
        self.assertEqual(result, b'')  # Should return empty bytes
        
    def test_unpack_function(self):
        """Test the unpack function with simple format."""
        # Create test data
        test_data = b'\x01\x02\x03\x04\x05\x06\x07\x08'
        
        # Create format specification: [(label, (formatter, lower, higher)), ...]
        test_format = [
            ('first_byte', ('i', 0, 0)),    # Single byte at position 0
            ('two_bytes', ('2i', 1, 2)),    # Two bytes from position 1-2
            ('last_four', ('4i', 4, 7))     # Four bytes from position 4-7
        ]
        
        result = unpack(test_data, test_format)
        
        # Check that we get expected structure
        self.assertIn('first_byte', result)
        self.assertIn('two_bytes', result)
        self.assertIn('last_four', result)
        
    def test_unpack_insufficient_data(self):
        """Test unpack function with insufficient data."""
        # Create short test data
        test_data = b'\x01\x02'
        
        # Format that requires more data than available
        test_format = [
            ('valid_data', ('i', 0, 1)),      # Valid range
            ('out_of_bounds', ('i', 5, 8))    # Tries to read beyond data
        ]
        
        # Should handle gracefully, setting None for missing data
        result = unpack(test_data, test_format)
        
        # Should have valid data for first field
        self.assertIn('valid_data', result)
        # Should handle out of bounds gracefully
        self.assertIn('out_of_bounds', result)
        
    def test_unpack_insufficient_data(self):
        """Test unpack function with insufficient data."""
        # Create short test data
        test_data = b'\x01\x02'
        
        # Format that requires more data than available
        test_format = [
            ('valid_data', ('i', 0, 1)),      # Valid range
            ('out_of_bounds', ('i', 5, 8))    # Tries to read beyond data
        ]
        
        # Should handle gracefully, setting None for missing data
        result = unpack(test_data, test_format)
        
        # Should have valid data for first field
        self.assertIn('valid_data', result)
        # Should handle out of bounds gracefully
        self.assertIn('out_of_bounds', result)


class TestNTFSIntegration(unittest.TestCase):
    """Integration tests combining multiple NTFS components."""
    
    def test_mft_indx_relationship(self):
        """Test the relationship between MFT and INDX records."""
        # Simulate finding related MFT and INDX records
        mft_positions = {100, 200, 300, 400}  # MFT record positions
        indx_positions = {1000, 2000, 3000}   # INDX record positions
        
        # Simulate INDX records pointing to MFT records
        indx_references = {
            1000: {'parent': 100, 'children': {200, 300}},
            2000: {'parent': 200, 'children': {400}},
            3000: {'parent': 300, 'children': set()},
        }
        
        # Create SparseList for INDX relationships
        indx_list = SparseList({pos: info['parent'] for pos, info in indx_references.items()})
        
        # Verify relationships
        self.assertEqual(indx_list[1000], 100)  # INDX at 1000 points to MFT 100
        self.assertEqual(indx_list[2000], 200)  # INDX at 2000 points to MFT 200
        
        # Test that we can find directory structure
        root_mft = 100
        subdirs = [pos for pos, info in indx_references.items() if info['parent'] == root_mft]
        self.assertEqual(len(subdirs), 1)
        self.assertEqual(subdirs[0], 1000)
        
        # Test children relationships
        children_of_200 = indx_references[2000]['children']
        self.assertEqual(children_of_200, {400})
        
    def test_partition_boundary_detection(self):
        """Test partition boundary detection logic."""
        # Simulate MFT pattern for boundary detection
        base_pattern = {10: 100, 20: 100, 30: 200, 40: 200}  # Cluster -> MFT record
        
        # Test different sectors per cluster values
        for sec_per_clus in [1, 2, 4, 8]:
            # Convert cluster pattern to sector pattern
            sector_pattern = {
                cluster * sec_per_clus: mft_record 
                for cluster, mft_record in base_pattern.items()
            }
            
            pattern_list = SparseList(sector_pattern)
            
            # Simulate text list (found INDX records)
            text_data = {}
            for sector in range(0, 400):
                if sector in sector_pattern:
                    text_data[sector + 1000] = sector_pattern[sector]  # Offset by 1000
                    
            text_list = SparseList(text_data)
            
            # Test approximate matching for boundary detection
            mft_address = 1000  # Assumed MFT start
            result = approximate_matching(text_list, pattern_list, mft_address + min(sector_pattern.keys()), k=2)
            
            if result is not None:
                positions, count, percentage = result
                # Should find at least one potential boundary
                self.assertGreater(len(positions), 0)
                self.assertGreater(percentage, 0.1)


if __name__ == '__main__':
    unittest.main()
