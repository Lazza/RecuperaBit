"""End-to-end tests for RecuperaBit NTFS recovery.

This module uses pre-built reference NTFS images to test complete recovery workflows.
"""

import unittest
import tempfile
import os
import shutil
import hashlib
from pathlib import Path
from typing import Dict
import logging

from recuperabit.fs.ntfs import NTFSPartition, NTFSScanner
from tests.reference_image import ensure_reference_image
import main  # Import main module to access interpret function


class TestNTFSE2E(unittest.TestCase):
    """End-to-end tests for NTFS recovery."""
    
    @classmethod
    def setUpClass(cls):
        """Set up class-level fixtures."""
        # Ensure reference image exists and is valid
        try:
            cls.ref_image = ensure_reference_image()
            logging.info(f"Using reference NTFS image: {cls.ref_image.image_path}")
        except (FileNotFoundError, ValueError) as e:
            raise unittest.SkipTest(f"Reference image not available: {e}")
            
        # Get expected file hashes from reference image
        cls.expected_files = cls.ref_image.get_expected_files()
        
        if not cls.expected_files:
            raise unittest.SkipTest("No expected files in reference image metadata")
            
        logging.info(f"Reference image contains {len(cls.expected_files)} test files")
        
        # Set up temp directory for working files
        cls.test_dir = tempfile.mkdtemp(prefix='recuperabit_e2e_')
        cls.recovery_dir = os.path.join(cls.test_dir, 'recovered')
        os.makedirs(cls.recovery_dir, exist_ok=True)
        
        logging.basicConfig(level=logging.DEBUG)
        
    @classmethod
    def tearDownClass(cls):
        """Clean up class-level fixtures."""
        # Clean up test directory
        if hasattr(cls, 'test_dir') and os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir)
            
    def setUp(self):
        """Set up test fixtures."""
        # Create a temporary copy of the reference image for this test
        self.image_path = os.path.join(self.test_dir, f'test_ntfs_{id(self)}.img')
        self.ref_image.copy_to_temp(Path(self.image_path))
        
    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up the temporary image copy
        if hasattr(self, 'image_path') and os.path.exists(self.image_path):
            os.remove(self.image_path)

    def _scan_image_with_scanner(self, scanner_class: type[NTFSScanner]) -> Dict[int, NTFSPartition]:
        """Scan the image with the given scanner class."""
        # Keep file handle open and return it along with partitions
        img_file = open(self.image_path, 'rb')
        scanner = scanner_class(img_file)

        # Feed sectors to scanner
        sector_size = 512
        sector_index = 0
        
        while True:
            img_file.seek(sector_index * sector_size)
            sector = img_file.read(sector_size)
            
            if len(sector) < sector_size:
                break
                
            result = scanner.feed(sector_index, sector)
            if result:
                logging.debug(f"Found {result} at sector {sector_index}")
                
            sector_index += 1
            
        # Get partitions
        partitions = scanner.get_partitions()
        # Store the file handle so it doesn't get closed
        self._img_file = img_file
        return partitions

    def _close_image_file(self):
        """Close the image file handle."""
        if hasattr(self, '_img_file') and self._img_file:
            self._img_file.close()
            self._img_file = None
            
    def _recover_files_from_partition(self, partition: NTFSPartition, partition_id: int) -> Dict[str, bytes]:
        """Recover files from a partition using high-level interpret function with proper hierarchy."""
        # Create temporary recovery directory
        recovery_dir = os.path.join(self.test_dir, f'recovered_partition_{partition_id}')
        os.makedirs(recovery_dir, exist_ok=True)
        
        # Create shorthands structure like main.py
        parts = {0: partition}  # Simple mapping for our single partition
        shorthands = [(0, 0)]   # (index, partition_key) pairs
        
        try:
            # Use the high-level interpret function to restore the root directory
            # This will properly handle filesystem hierarchy, directories, etc.
            main.interpret('restore', ['0', '5'], parts, shorthands, recovery_dir)  # '5' is typically the root directory
            
            # Collect all recovered files and their content
            recovered_files = {}
            
            # Walk through the recovered directory structure
            partition_dir = os.path.join(recovery_dir, 'Partition0', 'Root')
            if os.path.exists(partition_dir):
                for root, dirs, files in os.walk(partition_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Get relative path from partition directory
                        relative_path = os.path.relpath(file_path, partition_dir)
                        
                        try:
                            with open(file_path, 'rb') as f:
                                content = f.read()
                            recovered_files[relative_path] = content
                            logging.info(f"Recovered file: {relative_path} ({len(content)} bytes)")
                        except Exception as e:
                            logging.error(f"Error reading recovered file {relative_path}: {e}")
            
            return recovered_files
            
        except Exception as e:
            logging.error(f"Error during recovery: {e}")
            return {}
        finally:
            # Clean up recovery directory
            if os.path.exists(recovery_dir):
                shutil.rmtree(recovery_dir, ignore_errors=True)
        
    def _compare_files(self, original_hashes: Dict[str, str], 
                      recovered_files: Dict[str, bytes]) -> Dict[str, bool]:
        """Compare original and recovered files, handling path normalization."""
        results = {}
        
        # Normalize recovered file paths by removing Root/ prefix
        
        print(f"DEBUG: Expected files: {list(original_hashes.keys())}")
        print(f"DEBUG: Normalized recovered files: {list(recovered_files.keys())}")
        
        expected_recovered_files = [filename for filename in list(recovered_files.keys()) if filename in original_hashes.keys()]
        print(f"DEBUG: Matching recovered files: {expected_recovered_files} ({len(expected_recovered_files)} / {len(original_hashes)})")

        # Check how many files were recovered successfully
        for filename, original_hash in original_hashes.items():
            if filename in recovered_files:
                recovered_file = recovered_files[filename]
                recovered_hash = hashlib.sha256(recovered_file).hexdigest()
                results[filename] = (original_hash == recovered_hash)
                if results[filename]:
                    logging.info(f"✓ {filename}: Recovery successful ({len(recovered_file)} bytes)")
                else:
                    logging.error(f"✗ {filename}: Hash mismatch! Expected: {original_hash}, Got: {recovered_hash}")
                    # Print first 64 bytes of recovered content vs the original content for debugging
                    logging.error(f"  Recovered content (first 64 bytes): {recovered_file[:64]}")
                    with open(self.ref_image.get_reference_files_dir() / filename, 'rb') as original_file:
                        original_content = original_file.read(64)
                    logging.error(f"  Original content (first 64 bytes): {original_content[:64]}")
            else:
                results[filename] = False
                logging.error(f"✗ {filename}: File not recovered")
                
        return results
        
    def test_basic_ntfs_recovery(self):
        """Test basic NTFS file recovery using reference image."""
        print(f"DEBUG: Using reference NTFS image at {self.image_path}")
        
        try:
            # Test recovery with standard scanner
            partitions = self._scan_image_with_scanner(NTFSScanner)
            self.assertGreater(len(partitions), 0, "No NTFS partitions found")
            
            # Recover files from the LARGEST partition (most likely to contain user data)
            if not partitions:
                self.fail("No NTFS partitions found")
                
            # Find the largest partition by number of files (user data indicator)
            largest_partition_id = None
            largest_partition = None
            max_files = 0
            
            print(f"DEBUG: Found {len(partitions)} partitions:")
            for partition_id, partition in partitions.items():
                file_count = len(partition.files) if hasattr(partition, 'files') else 0
                print(f"  Partition {partition_id}: {file_count} files, offset {partition.offset}")
                
                if file_count > max_files:
                    max_files = file_count
                    largest_partition_id = partition_id
                    largest_partition = partition
                    
            if largest_partition is None:
                self.fail("No partition with files found")
                
            print(f"DEBUG: Processing largest partition {largest_partition_id} with {max_files} files at offset {largest_partition.offset}")
            
            # Recover files from the largest partition only
            all_recovered_files = self._recover_files_from_partition(largest_partition, largest_partition_id)

            for filename, content in all_recovered_files.items():
                print(f"DEBUG: Recovered file '{filename}' with content size {len(content)} bytes")

            # Compare results using expected files from reference image
            comparison = self._compare_files(self.expected_files, all_recovered_files)
            
            # Check that at least some files were recovered correctly
            successful_recoveries = sum(1 for success in comparison.values() if success)
            total_files = len(self.expected_files)
            
            self.assertGreater(successful_recoveries, 0, "No files recovered successfully")
            
            # We expect most files to be recovered (allowing for some edge cases)
            recovery_rate = successful_recoveries / total_files
            self.assertAlmostEqual(recovery_rate, 1.0, 
                              f"Low recovery rate: {recovery_rate:.2%} ({successful_recoveries}/{total_files})")
            
            # Log success for visibility  
            print(f"SUCCESS: Hierarchical recovery rate {recovery_rate:.2%} ({successful_recoveries}/{total_files})")
            print(f"✅ All {total_files} files found with correct filesystem hierarchy!")
            print(f"✅ High-level recovery APIs working correctly!")
            print(f"✅ Largest partition selection working!")
        finally:
            # Always close the image file handle
            self._close_image_file()
    

if __name__ == '__main__':
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    unittest.main(verbosity=2)
