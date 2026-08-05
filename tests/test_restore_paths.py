import tempfile
import unittest
from pathlib import Path

from recuperabit import logic
from recuperabit.fs.core_types import DiskScanner, File, Partition


class PayloadFile(File):
    def __init__(self, index, name, payload=b"payload"):
        super().__init__(index=index, name=name, size=len(payload))
        self.payload = payload

    def get_content(self, partition):
        return self.payload


def partition_with_child(child):
    root = File(5, "Root", 0, is_directory=True, is_ghost=True)
    child.set_parent(root.index)
    root.add_child(child)

    partition = Partition("ntfs", root.index, DiskScanner(None))
    partition.add_file(root)
    partition.add_file(child)
    partition.set_root(root)
    return partition


class RecursiveRestorePathTests(unittest.TestCase):
    def test_restore_keeps_normal_child_under_output_directory(self):
        child = PayloadFile(10, "report.txt", b"safe")
        partition = partition_with_child(child)

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "restore"

            logic.recursive_restore(child, partition, str(output_dir))

            self.assertEqual((output_dir / "Root" / "report.txt").read_bytes(), b"safe")

    def test_restore_rejects_relative_parent_traversal(self):
        child = PayloadFile(11, "../../../escaped.txt", b"escaped")
        partition = partition_with_child(child)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "restore"
            escaped_path = tmp_path / "escaped.txt"

            logic.recursive_restore(child, partition, str(output_dir))

            self.assertFalse(escaped_path.exists())

    def test_restore_rejects_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            absolute_path = tmp_path / "absolute.txt"
            child = PayloadFile(12, str(absolute_path), b"escaped")
            partition = partition_with_child(child)

            logic.recursive_restore(child, partition, str(tmp_path / "restore"))

            self.assertFalse(absolute_path.exists())


if __name__ == "__main__":
    unittest.main()
