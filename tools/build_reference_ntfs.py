#!/usr/bin/env python3
"""Build reference NTFS filesystem image for E2E tests.

This script creates a reference NTFS filesystem image by:
1. Creating a loop-mounted NTFS filesystem
2. Copying reference test files to it
3. Unmounting and saving the image
4. Computing checksums for both the image and source files
5. Storing metadata for validation

Usage:
    python tools/build_reference_ntfs.py [--size SIZE_MB] [--output OUTPUT_PATH]
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List

import gzip

class NTFSImageBuilder:
    """Builder for reference NTFS filesystem images."""
    
    def __init__(self, size_mb: int = 100, output_path: str = None, compress: bool = True):
        self.size_mb = size_mb
        self.output_path = output_path or "tests/data/reference_ntfs.img"
        self.metadata_path = self.output_path.replace('.img', '.json')
        self.reference_files_dir = Path("tests/data/reference_files")
        self.compress = compress
        
        # Set up logging
        logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
        self.logger = logging.getLogger(__name__)
        
    def _check_requirements(self) -> None:
        """Check if required tools are available."""
        required_tools = ['mkfs.ntfs', 'losetup', 'mount', 'umount', 'sync']
        missing_tools = []
        
        for tool in required_tools:
            if shutil.which(tool) is None:
                missing_tools.append(tool)
                
        if missing_tools:
            raise RuntimeError(f"Missing required tools: {', '.join(missing_tools)}")
            
        # Check if running as root (needed for loop devices)
        if os.geteuid() != 0:
            raise RuntimeError("This script must be run as root to create loop devices")
            
    def _compute_file_hash(self, filepath: Path) -> str:
        """Compute SHA256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
        
    def _compute_directory_hash(self, directory: Path) -> Dict[str, str]:
        """Compute hashes for all files in a directory recursively."""
        file_hashes = {}
        
        for filepath in directory.rglob('*'):
            if filepath.is_file():
                relative_path = filepath.relative_to(directory)
                file_hashes[str(relative_path)] = self._compute_file_hash(filepath)
                self.logger.info(f"Hashed {relative_path}: {file_hashes[str(relative_path)][:16]}...")
                
        return file_hashes
        
    def _create_empty_image(self, image_path: Path) -> None:
        """Create an empty disk image file."""
        self.logger.info(f"Creating {self.size_mb}MB empty image at {image_path}")
        
        with open(image_path, 'wb') as f:
            f.seek(self.size_mb * 1024 * 1024 - 1)
            f.write(b'\0')
            
    def _format_ntfs(self, image_path: Path) -> None:
        """Format the image as NTFS."""
        self.logger.info("Formatting image as NTFS...")
        
        cmd = ['mkfs.ntfs', '-F', '-f', str(image_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to format NTFS: {result.stderr}")
            
    def _setup_loop_device(self, image_path: Path) -> str:
        """Set up loop device for the image."""
        self.logger.info("Setting up loop device...")
        
        cmd = ['losetup', '--find', '--show', str(image_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to set up loop device: {result.stderr}")
            
        loop_device = result.stdout.strip()
        self.logger.info(f"Created loop device: {loop_device}")
        return loop_device
        
    def _cleanup_loop_device(self, loop_device: str) -> None:
        """Clean up loop device."""
        self.logger.info(f"Cleaning up loop device: {loop_device}")
        
        cmd = ['losetup', '-d', loop_device]
        subprocess.run(cmd, capture_output=True, text=True)
        
    def _mount_filesystem(self, loop_device: str, mount_point: Path) -> None:
        """Mount the NTFS filesystem."""
        self.logger.info(f"Mounting {loop_device} at {mount_point}")

        cmd = ['mount', '-t', 'ntfs-3g', '-o', 'sync', loop_device, str(mount_point)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to mount filesystem: {result.stderr}")
            
    def _unmount_filesystem(self, mount_point: Path) -> None:
        """Unmount the filesystem."""
        self.logger.info(f"Unmounting {mount_point}")
        
        cmd = ['umount', str(mount_point)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            self.logger.warning(f"Failed to unmount cleanly: {result.stderr}")
            
    def _copy_files(self, mount_point: Path) -> None:
        """Copy reference files to the mounted filesystem."""
        self.logger.info("Copying reference files to mounted filesystem...")
        
        if not self.reference_files_dir.exists():
            raise RuntimeError(f"Reference files directory not found: {self.reference_files_dir}")
            
        # Copy all files and directories
        for item in self.reference_files_dir.iterdir():
            dest = mount_point / item.name
            
            if item.is_file():
                shutil.copy2(item, dest)
                self.logger.info(f"Copied file: {item.name}")
            elif item.is_dir():
                shutil.copytree(item, dest)
                self.logger.info(f"Copied directory: {item.name}")
                
        # Create alternate data stream (if supported)
        try:
            ads_file = mount_point / "file_with_ads.txt"
            if ads_file.exists():
                # Try to create ADS using attr command if available
                if shutil.which('attr'):
                    cmd = ['attr', '-s', 'stream1', '-V', 'ADS content', str(ads_file)]
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode == 0:
                        self.logger.info("Created alternate data stream")
                    else:
                        self.logger.warning("Failed to create ADS, not supported")
                else:
                    self.logger.warning("attr tool not available, skipping ADS creation")
        except Exception as e:
            self.logger.warning(f"Could not create alternate data stream: {e}")
            
    def _save_metadata(self, image_path: Path, file_hashes: Dict[str, str]) -> None:
        """Save metadata about the image and source files."""
        self.logger.info("Computing image hash and saving metadata...")
        
        # Compute image hash
        image_hash = self._compute_file_hash(image_path)
        
        # Get image size
        image_size = image_path.stat().st_size
        
        metadata = {
            "version": "1.0",
            "created_by": "build_reference_ntfs.py",
            "size_mb": self.size_mb,
            "image_size_bytes": image_size,
            "image_hash": image_hash,
            "reference_files_hashes": file_hashes,
            "file_count": len(file_hashes),
            "notes": "Reference NTFS filesystem for RecuperaBit E2E tests"
        }
        
        with open(self.metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2, sort_keys=True)
            
        self.logger.info(f"Saved metadata to {self.metadata_path}")
        self.logger.info(f"Image hash: {image_hash}")
        
    def build(self) -> None:
        """Build the reference NTFS image."""
        self.logger.info("Starting NTFS reference image build...")
        
        # Check requirements
        self._check_requirements()
        
        # Prepare paths
        image_path = Path(self.output_path)
        image_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Compute hashes of source files
        self.logger.info("Computing hashes of reference files...")
        file_hashes = self._compute_directory_hash(self.reference_files_dir)
        
        loop_device = None
        temp_mount = None
        
        try:
            # Create and format image
            self._create_empty_image(image_path)
            self._format_ntfs(image_path)
            
            # Set up loop device
            loop_device = self._setup_loop_device(image_path)
            
            # Create temporary mount point
            temp_mount = Path(tempfile.mkdtemp(prefix="ntfs_build_"))
            
            # Mount, copy files, unmount
            self._mount_filesystem(loop_device, temp_mount)
            self._copy_files(temp_mount)
            
            # Sync to ensure all data is written
            subprocess.run(['sync', str(temp_mount)], check=True)

            self._unmount_filesystem(temp_mount)
            
            # Save metadata
            self._save_metadata(image_path, file_hashes)
            
            self.logger.info(f"Successfully created reference NTFS image: {image_path}")
            self.logger.info(f"Image size: {image_path.stat().st_size / (1024*1024):.1f} MB")

            # Compress image
            if self.compress:
                self.logger.info("Compressing image with gzip...")
                with open(image_path, 'rb') as f_in, gzip.open(f"{image_path}.gz", 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
                image_path.unlink()  # Remove uncompressed image

        finally:
            # Clean up
            if loop_device:
                self._cleanup_loop_device(loop_device)
                
            if temp_mount and temp_mount.exists():
                shutil.rmtree(temp_mount)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Build reference NTFS image for E2E tests")
    parser.add_argument('--size', type=int, default=100, 
                       help='Image size in MB (default: 100)')
    parser.add_argument('--output', type=str, 
                       default='tests/data/reference_ntfs.img',
                       help='Output image path (default: tests/data/reference_ntfs.img)')
    
    args = parser.parse_args()
    
    builder = NTFSImageBuilder(size_mb=args.size, output_path=args.output)
    
    try:
        builder.build()
        print(f"\n✓ Success! Reference NTFS image created at: {args.output}")
        print(f"✓ Metadata saved at: {args.output.replace('.img', '.json')}")
        print("\nNext steps:")
        print("1. Add the .img file to Git LFS: git lfs track '*.img'")
        print("2. Commit both the image and metadata files")
        print("3. The E2E tests will now use this reference image")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        return 1
        
    return 0


if __name__ == '__main__':
    exit(main())
