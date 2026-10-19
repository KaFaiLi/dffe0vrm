"""Run with python -B -m unittest -v."""

import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zlib

from pack import pack_folder
from unpack import read_bundle, unpack_bundle


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.bundle = self.root / "bundle.txt"
        self.files = {
            "main.py": b"print('hello')\r\n" * 100,
            "nested/module.py": b"# nested\n",
            "skills/demo/SKILL.md": "# Demo\nCafé\n".encode(),
            "skills/demo/references/data.md": b"# Dataset\n",
            "assets/data.bin": bytes(range(256)),
            "empty.txt": b"",
        }
        for name, content in self.files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def pack(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            pack_folder(self.source, self.bundle, **kwargs)

    def restore(self, target):
        with contextlib.redirect_stdout(io.StringIO()):
            unpack_bundle(self.bundle, target)

    def assert_restored(self, target, expected):
        actual = {
            p.relative_to(target).as_posix(): p.read_bytes()
            for p in target.rglob("*") if p.is_file()
        }
        self.assertEqual(actual, expected)

    def test_round_trip_all_formats_and_file_selection(self):
        for compress in (True, False):
            for all_files in (True, False):
                with self.subTest(compress=compress, all_files=all_files):
                    self.pack(compress=compress, all_files=all_files)
                    target = self.root / f"restore-{compress}-{all_files}"
                    self.restore(target)
                    expected = {
                        name: data for name, data in self.files.items()
                        if all_files or name.endswith(".py")
                    }
                    self.assert_restored(target, expected)

    def test_compression_is_smaller_and_deterministic(self):
        self.pack(all_files=True, compress=False)
        legacy_size = self.bundle.stat().st_size
        self.pack(all_files=True)
        first = self.bundle.read_bytes()
        self.assertLess(len(first), legacy_size)
        self.assertTrue(first.isascii())
        self.pack(all_files=True)
        self.assertEqual(first, self.bundle.read_bytes())

    def test_empty_source(self):
        self.source = self.root / "empty"
        self.source.mkdir()
        self.pack(all_files=True)
        target = self.root / "restored-empty"
        self.restore(target)
        self.assertEqual(read_bundle(self.bundle)["file_count"], 0)
        self.assert_restored(target, {})

    def test_output_is_not_included_in_itself(self):
        self.bundle = self.source / "bundle.txt"
        self.pack(all_files=True)
        self.pack(all_files=True)
        self.assertEqual(read_bundle(self.bundle)["file_count"], len(self.files))

    def test_tracked_only_from_package_subdirectory(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "source"], check=True)
        (self.source / "untracked.txt").write_text("not included")
        (self.root / "outside.txt").write_text("not included")
        self.pack(all_files=True, tracked_only=True)
        target = self.root / "tracked"
        self.restore(target)
        self.assert_restored(target, self.files)

    def test_checksum_failure_does_not_create_output(self):
        self.pack(all_files=True)
        envelope = json.loads(self.bundle.read_text())
        envelope["sha256"] = "0" * 64
        self.bundle.write_text(json.dumps(envelope))
        target = self.root / "corrupt"
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.restore(target)
        self.assertFalse(target.exists())

    def test_invalid_compressed_streams(self):
        self.pack(all_files=True)
        envelope = json.loads(self.bundle.read_text())
        compressed = base64.b64decode(envelope["data"])
        invalid = ["!invalid", None, base64.b64encode(b"invalid zlib").decode()]
        invalid += [base64.b64encode(data).decode() for data in
                    (compressed[:-1], compressed + b"trailing")]
        for data in invalid:
            with self.subTest(data=str(data)[:20]):
                envelope["data"] = data
                self.bundle.write_text(json.dumps(envelope))
                with self.assertRaisesRegex(ValueError, "Invalid compressed bundle"):
                    read_bundle(self.bundle)

    def test_unsupported_compression(self):
        self.pack(all_files=True)
        envelope = json.loads(self.bundle.read_text())
        envelope["compression"] = "unknown"
        self.bundle.write_text(json.dumps(envelope))
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            read_bundle(self.bundle)

    def test_path_traversal_in_legacy_and_compressed_bundles(self):
        for format_name in ("PYBUNDLE1", "FILEBUNDLE1"):
            for compressed in (False, True):
                with self.subTest(format=format_name, compressed=compressed):
                    bundle = {
                        "format": format_name, "file_count": 1,
                        "files": [{"path": "../escape.py", "content": ""}],
                    }
                    if compressed:
                        payload = json.dumps(bundle).encode()
                        bundle = {
                            "format": "ZBUNDLE1", "compression": "zlib",
                            "encoding": "base64",
                            "sha256": hashlib.sha256(payload).hexdigest(),
                            "data": base64.b64encode(zlib.compress(payload)).decode(),
                        }
                    self.bundle.write_text(json.dumps(bundle))
                    with self.assertRaisesRegex(ValueError, "Unsafe path"):
                        self.restore(self.root / "unsafe")
                    self.assertFalse((self.root / "escape.py").exists())

    def test_cli_default_and_legacy_option(self):
        scripts = Path(__file__).resolve().parent
        for flags in ([], ["--no-compress"]):
            subprocess.run(
                [sys.executable, "-B", str(scripts / "pack.py"), str(self.source),
                 "--all-files", "-o", str(self.bundle), *flags],
                check=True, capture_output=True,
            )
            self.assertEqual(json.loads(self.bundle.read_text())["format"],
                             "FILEBUNDLE1" if flags else "ZBUNDLE1")
            target = self.root / ("cli-legacy" if flags else "cli-compressed")
            subprocess.run(
                [sys.executable, "-B", str(scripts / "unpack.py"),
                 str(self.bundle), "-o", str(target)],
                check=True, capture_output=True,
            )
            self.assert_restored(target, self.files)


if __name__ == "__main__":
    unittest.main()
