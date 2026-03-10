"""Reference NTFS image utilities for E2E tests."""

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple

import gzip


class ReferenceNTFSImage:
    """Handler for reference NTFS filesystem images used in E2E tests."""
    
    def __init__(self, image_path: str = "tests/data/reference_ntfs.img.gz"):
        self.image_path = Path(image_path)
        # Remove both .img and .gz to get metadata path
        if self.image_path.suffix == '.gz':
            self.metadata_path = self.image_path.with_suffix('').with_suffix('.json')
        else:
            self.metadata_path = self.image_path.with_suffix('.json')
        self.logger = logging.getLogger(__name__)
        
    def exists(self) -> bool:
        """Check if the reference image exists."""
        print(self.image_path, self.metadata_path)
        return self.image_path.exists() and self.metadata_path.exists()
    
    def is_compressed(self) -> bool:
        """Check if the reference image is compressed (e.g., .img.gz)."""
        return self.image_path.suffix == '.gz'
        
    def _compute_file_hash(self, filepath: Path, compressed: bool = False) -> str:
        """Compute SHA256 hash of a file."""
        sha256_hash = hashlib.sha256()
        opener = gzip.open if compressed else open
        with opener(filepath, "rb") as f:
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
                
        return file_hashes
        
    def validate(self) -> Tuple[bool, Optional[str]]:
        """Validate that the reference image is up-to-date and uncorrupted.
        
        Returns:
            (is_valid, error_message)
        """
        if not self.exists():
            return False, f"Reference image not found: {self.image_path}"
            
        try:
            # Load metadata
            with open(self.metadata_path, 'r') as f:
                metadata = json.load(f)
                
            # Validate image hash
            current_image_hash = self._compute_file_hash(self.image_path, self.is_compressed())
            expected_image_hash = metadata.get('image_hash')
            
            if current_image_hash != expected_image_hash:
                return False, f"Image hash mismatch: expected {expected_image_hash}, got {current_image_hash}"
                
            # Validate source files hash (to detect if reference files changed)
            reference_files_dir = Path("tests/data/reference_files")
            if reference_files_dir.exists():
                current_files_hash = self._compute_directory_hash(reference_files_dir)
                expected_files_hash = metadata.get('reference_files_hashes', {})
                
                if current_files_hash != expected_files_hash:
                    return False, "Reference files have changed, image needs to be rebuilt"
                    
            return True, None
            
        except Exception as e:
            return False, f"Validation error: {e}"
            
    def get_expected_files(self) -> Dict[str, str]:
        """Get the expected file hashes from the reference image metadata.
        
        Returns:
            Dictionary mapping relative file paths to their SHA256 hashes
        """
        if not self.metadata_path.exists():
            return {}
            
        try:
            with open(self.metadata_path, 'r') as f:
                metadata = json.load(f)
            return metadata.get('reference_files_hashes', {})
        except Exception as e:
            self.logger.error(f"Failed to load metadata: {e}")
            return {}
        
    def get_reference_files_dir(self) -> Path:
        """Get the directory containing the original reference files."""
        return self.metadata_path.parent / "reference_files"
            
    def copy_to_temp(self, temp_path: Path) -> None:
        """Copy the reference image to a temporary location for testing.
        
        Args:
            temp_path: Path where to copy the image
        """
        if not self.exists():
            raise FileNotFoundError(f"Reference image not found: {self.image_path}")

        if self.is_compressed():
            with gzip.open(self.image_path, 'rb') as f_in, open(temp_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            shutil.copy2(self.image_path, temp_path)
        self.logger.debug(f"Copied reference image to {temp_path}")
        
    def get_info(self) -> Dict:
        """Get information about the reference image.
        
        Returns:
            Dictionary with image metadata
        """
        if not self.metadata_path.exists():
            return {}
            
        try:
            with open(self.metadata_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load metadata: {e}")
            return {}


def ensure_reference_image() -> ReferenceNTFSImage:
    """Ensure reference NTFS image exists and is valid.
    
    Returns:
        ReferenceNTFSImage instance
        
    Raises:
        FileNotFoundError: If image doesn't exist
        ValueError: If image is corrupted or outdated
    """
    ref_image = ReferenceNTFSImage()
    
    if not ref_image.exists():
        raise FileNotFoundError(
            "Reference NTFS image not found. Please run: "
            "sudo python tools/build_reference_ntfs.py"
        )
        
    is_valid, error = ref_image.validate()
    if not is_valid:
        raise ValueError(
            f"Reference NTFS image validation failed: {error}. "
            "Please rebuild with: sudo python tools/build_reference_ntfs.py"
        )
        
    return ref_image
