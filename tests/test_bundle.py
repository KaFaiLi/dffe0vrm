import hashlib
import io
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

from bundle import pack_folder, unpack_bundle


REPOSITORY = Path(__file__).resolve().parents[1]


def file_hashes(folder: Path) -> dict[str, str]:
    result = {}
    for path in folder.rglob("*"):
        if path.is_file():
            with path.open("rb") as data:
                result[path.relative_to(folder).as_posix()] = hashlib.file_digest(data, "sha256").hexdigest()
    return result


def tar_bytes(records: list[tuple[str, bytes]], entry_type: bytes = tarfile.REGTYPE) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, content in records:
            member = tarfile.TarInfo(name)
            member.type = entry_type
            member.size = len(content)
            if entry_type in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                member.linkname = "../outside"
            archive.addfile(member, io.BytesIO(content))
    return buffer.getvalue()


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bundle-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.archive = self.root / "bundle.tar.xz"
        self.output = self.root / "restored"

    def write_source(self, name: str, content: bytes) -> Path:
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def assert_rejected(self, archive_data: bytes):
        self.archive.write_bytes(archive_data)
        before = set(self.root.iterdir())
        with self.assertRaises((ValueError, OSError, EOFError, tarfile.TarError, lzma.LZMAError)):
            unpack_bundle(self.archive, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(set(self.root.iterdir()), before, "Temporary extraction was not cleaned up")

    def test_round_trip_preserves_complete_paths_and_bytes(self):
        files = {
            "UPPER.PY": b"print('upper')\r\n",
            "nested/code.py": b"# coding: latin-1\r\nx = '\xff'\n",
            "nested/zero.bin": b"",
            "binary.bin": bytes(range(256)) * 32,
            "unicode-\u6d4b\u8bd5/\u00e9.txt": b"no final newline",
            "long-" + "a" * 110 + "/nested.txt": b"long PAX path",
        }
        for name, content in files.items():
            self.write_source(name, content)
        (self.source / "empty-directory").mkdir()
        packed = pack_folder(self.source, self.archive, all_files=True)
        restored = unpack_bundle(self.archive, self.output)
        self.assertEqual(file_hashes(self.output), file_hashes(self.source))
        self.assertEqual(restored, packed)
        self.assertEqual(packed.file_count, len(files))
        self.assertEqual(packed.content_bytes, sum(map(len, files.values())))
        self.assertEqual(packed.archive_bytes, self.archive.stat().st_size)
        self.assertFalse((self.output / "empty-directory").exists())

    def test_python_selection_includes_uppercase_extension(self):
        self.write_source("a.py", b"a")
        self.write_source("nested/UPPER.PY", b"upper")
        self.write_source("skip.txt", b"skip")
        pack_folder(self.source, self.archive)
        unpack_bundle(self.archive, self.output)
        self.assertEqual(set(file_hashes(self.output)), {"a.py", "nested/UPPER.PY"})

    def test_empty_selection_restores_empty_folder(self):
        self.write_source("not-python.txt", b"excluded")
        packed = pack_folder(self.source, self.archive)
        restored = unpack_bundle(self.archive, self.output)
        self.assertEqual(packed.file_count, 0)
        self.assertEqual(restored, packed)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_archive_is_standard_tar_xz_and_ignores_metadata(self):
        path = self.write_source("a.py", b"a")
        pack_folder(self.source, self.archive)
        first = self.archive.read_bytes()
        os.utime(path, (946684800, 946684800))
        pack_folder(self.source, self.archive)
        self.assertEqual(first, self.archive.read_bytes())
        with tarfile.open(self.archive, "r:xz") as archive:
            member = archive.getmember("a.py")
            self.assertEqual((member.mtime, member.uid, member.gid), (0, 0, 0))
            self.assertEqual(archive.extractfile(member).read(), b"a")

    def test_output_inside_source_is_excluded_on_repeated_packs(self):
        self.write_source("a.py", b"a")
        output = self.source / "export.tar.xz"
        first_stats = pack_folder(self.source, output, all_files=True)
        first = output.read_bytes()
        second_stats = pack_folder(self.source, output, all_files=True)
        self.assertEqual(second_stats, first_stats)
        self.assertEqual(output.read_bytes(), first)
        unpack_bundle(output, self.output)
        self.assertEqual(set(file_hashes(self.output)), {"a.py"})

    def test_pack_failure_preserves_existing_archive_and_cleans_temporary(self):
        self.write_source("a.py", b"a")
        self.write_source("b.py", b"b")
        self.archive.write_bytes(b"previous archive")
        before = set(self.root.iterdir())
        original_addfile = tarfile.TarFile.addfile

        def fail_second(archive, member, data=None):
            if member.name == "b.py":
                raise OSError("simulated write failure")
            return original_addfile(archive, member, data)

        with mock.patch.object(tarfile.TarFile, "addfile", fail_second):
            with self.assertRaisesRegex(OSError, "simulated"):
                pack_folder(self.source, self.archive)
        self.assertEqual(self.archive.read_bytes(), b"previous archive")
        self.assertEqual(set(self.root.iterdir()), before)

    def test_source_growth_during_pack_is_rejected(self):
        path = self.write_source("a.py", b"a")
        original_addfile = tarfile.TarFile.addfile

        def grow_source(archive, member, data=None):
            original_addfile(archive, member, data)
            with path.open("ab") as output:
                output.write(b"changed")

        with mock.patch.object(tarfile.TarFile, "addfile", grow_source):
            with self.assertRaisesRegex(ValueError, "Source changed"):
                pack_folder(self.source, self.archive)
        self.assertFalse(self.archive.exists())
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_existing_destination_is_never_modified(self):
        self.write_source("a.py", b"archive data")
        pack_folder(self.source, self.archive)
        self.output.mkdir()
        (self.output / "a.py").write_bytes(b"existing data")
        with self.assertRaises(FileExistsError):
            unpack_bundle(self.archive, self.output)
        self.assertEqual((self.output / "a.py").read_bytes(), b"existing data")

    def test_existing_empty_destination_is_rejected(self):
        pack_folder(self.source, self.archive)
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            unpack_bundle(self.archive, self.output)
        self.assertTrue(self.output.is_dir())

    def test_missing_source_is_rejected_without_output(self):
        with self.assertRaises(NotADirectoryError):
            pack_folder(self.root / "missing", self.archive)
        self.assertFalse(self.archive.exists())

    def test_truncated_and_corrupted_xz_are_rejected(self):
        self.write_source("data.py", b"data\n" * 400000)
        pack_folder(self.source, self.archive)
        data = self.archive.read_bytes()
        for cut in (1, 6, 12, len(data) // 2):
            with self.subTest(truncated_bytes=cut):
                self.assert_rejected(data[:-cut])
        for index in (0, len(data) // 2, len(data) - 12):
            with self.subTest(corrupted_byte=index):
                damaged = bytearray(data)
                damaged[index] ^= 1
                self.assert_rejected(bytes(damaged))

    def test_invalid_later_tar_header_does_not_silently_omit_files(self):
        raw = bytearray(tar_bytes([("first", b"a"), ("second", b"b")]))
        raw[1024] ^= 1  # Break only the second member's header checksum.
        self.assert_rejected(lzma.compress(raw))

    def test_missing_tar_terminator_is_rejected(self):
        raw = tar_bytes([("file", b"a")])
        for length in (513, 1024, 1536, 2047):
            with self.subTest(tar_bytes=length):
                self.assert_rejected(lzma.compress(raw[:length]))

    def test_data_after_tar_terminator_is_rejected(self):
        raw = tar_bytes([("file", b"a")])
        self.assert_rejected(lzma.compress(raw + b"hidden"))

    def test_appended_data_and_second_xz_stream_are_rejected(self):
        data = lzma.compress(tar_bytes([("file", b"a")]))
        for suffix in (b"junk", b"\0", data):
            with self.subTest(suffix_length=len(suffix)):
                self.assert_rejected(data + suffix)

    def test_standard_xz_zero_padding_is_accepted(self):
        self.archive.write_bytes(lzma.compress(tar_bytes([("file", b"a")])) + b"\0" * 8)
        unpack_bundle(self.archive, self.output)
        self.assertEqual((self.output / "file").read_bytes(), b"a")

    def test_xz_without_integrity_check_is_rejected(self):
        self.assert_rejected(lzma.compress(tar_bytes([("file", b"a")]), check=lzma.CHECK_NONE))

    def test_unsafe_paths_are_rejected_without_outside_writes(self):
        names = ["../escape", "/absolute", "C:/absolute", "C:relative", "dir\\file", "a/../b", "a//b", "./file", "file:stream"]
        if os.name == "nt":
            names += ["CON", "nul.txt", "folder./file", "file ", "folder/a?b"]
        for name in names:
            with self.subTest(name=name):
                self.assert_rejected(lzma.compress(tar_bytes([("valid", b"a"), (name, b"bad")])))

    def test_duplicate_and_conflicting_paths_are_rejected(self):
        pairs = [("same", "same"), ("file", "file/child"), ("dir/child", "dir")]
        if os.name == "nt":
            pairs += [("FILE", "file"), ("Dir/one", "dir/two")]
        for first, second in pairs:
            with self.subTest(paths=(first, second)):
                self.assert_rejected(lzma.compress(tar_bytes([(first, b"a"), (second, b"b")])))

    def test_links_directories_and_special_entries_are_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            with self.subTest(entry_type=kind):
                self.assert_rejected(lzma.compress(tar_bytes([("entry", b"")], kind)))

    def test_source_symlink_is_rejected(self):
        target = self.write_source("real.py", b"a")
        link = self.source / "link.py"
        try:
            link.symlink_to(target)
        except OSError as error:
            self.skipTest(f"Creating symlinks is unavailable: {error}")
        with self.assertRaisesRegex(ValueError, "Links are not supported"):
            pack_folder(self.source, self.archive)
        self.assertFalse(self.archive.exists())

    def test_source_directory_symlink_is_rejected(self):
        folder = self.source / "real"
        folder.mkdir()
        (folder / "a.py").write_bytes(b"a")
        try:
            (self.source / "linked").symlink_to(folder, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Creating symlinks is unavailable: {error}")
        with self.assertRaisesRegex(ValueError, "Links are not supported"):
            pack_folder(self.source, self.archive)
        self.assertFalse(self.archive.exists())

    def test_output_symlink_is_rejected_without_modifying_target(self):
        original = self.root / "original"
        original.write_bytes(b"keep")
        try:
            self.archive.symlink_to(original)
        except OSError as error:
            self.skipTest(f"Creating symlinks is unavailable: {error}")
        with self.assertRaisesRegex(ValueError, "Output must not be a link"):
            pack_folder(self.source, self.archive)
        self.assertEqual(original.read_bytes(), b"keep")

    def test_unpack_write_failure_cleans_all_partial_files(self):
        self.write_source("a.py", b"a")
        self.write_source("b.py", b"b")
        pack_folder(self.source, self.archive)
        before = set(self.root.iterdir())
        original_copy = shutil.copyfileobj

        def fail_second(source, destination, length):
            if Path(destination.name).name == "b.py":
                destination.write(b"partial")
                raise OSError("simulated disk error")
            return original_copy(source, destination, length)

        with mock.patch.object(shutil, "copyfileobj", fail_second):
            with self.assertRaisesRegex(OSError, "simulated disk error"):
                unpack_bundle(self.archive, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(set(self.root.iterdir()), before)

    @unittest.skipUnless(shutil.which("git"), "Git is not installed")
    def test_git_selection_is_scoped_to_subfolder_and_missing_file_fails(self):
        subprocess.run(["git", "init", "-q", str(self.source)], check=True, capture_output=True)
        tracked = self.write_source("project/UPPER.PY", b"upper")
        self.write_source("project/asset.bin", b"asset")
        self.write_source("sibling.py", b"outside")
        self.write_source("project/\u6d4b\u8bd5.txt", b"unicode")
        subprocess.run(["git", "-C", str(self.source), "add", "."], check=True, capture_output=True)
        self.write_source("project/untracked.py", b"untracked")
        pack_folder(self.source / "project", self.archive, tracked_only=True)
        unpack_bundle(self.archive, self.output)
        self.assertEqual(set(file_hashes(self.output)), {"UPPER.PY"})
        pack_folder(self.source / "project", self.archive, all_files=True, tracked_only=True)
        unpack_bundle(self.archive, self.root / "all-tracked")
        self.assertEqual(set(file_hashes(self.root / "all-tracked")), {"UPPER.PY", "asset.bin", "\u6d4b\u8bd5.txt"})
        original = self.archive.read_bytes()
        tracked.unlink()
        with self.assertRaises(FileNotFoundError):
            pack_folder(self.source / "project", self.archive, tracked_only=True)
        self.assertEqual(self.archive.read_bytes(), original)

    def test_cli_defaults_and_clear_failure(self):
        self.write_source("a.py", b"a")
        result = subprocess.run(
            [sys.executable, str(REPOSITORY / "pack.py"), str(self.source)],
            cwd=self.root, capture_output=True, text=True, check=True,
        )
        self.assertIn("Packed 1 files", result.stdout)
        result = subprocess.run(
            [sys.executable, str(REPOSITORY / "unpack.py"), "python_bundle.tar.xz"],
            cwd=self.root, capture_output=True, text=True, check=True,
        )
        self.assertIn("Restored 1 files", result.stdout)
        self.assertEqual(file_hashes(self.root / "restored_project"), file_hashes(self.source))
        result = subprocess.run(
            [sys.executable, str(REPOSITORY / "unpack.py"), "python_bundle.tar.xz"],
            cwd=self.root, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("already exists", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
