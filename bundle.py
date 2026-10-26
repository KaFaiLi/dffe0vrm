"""Stream file paths and bytes through TAR/XZ compression and a text envelope."""

import base64
import binascii
from dataclasses import dataclass
import lzma
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile
from typing import BinaryIO


BUFFER_SIZE = 1024 * 1024
COMPRESSION_PRESET = 6
TEXT_HEADER = b"TARXZ64/1\n"


@dataclass(frozen=True)
class BundleStats:
    file_count: int
    content_bytes: int
    archive_bytes: int


class _Base64Writer:
    """Encode compressed bytes as ASCII lines without buffering the archive."""

    def __init__(self, destination: BinaryIO):
        self.destination = destination
        self.pending = b""
        destination.write(TEXT_HEADER)

    def write(self, data: bytes) -> int:
        # 57 input bytes produce a complete 76-character Base64 line. Keep
        # partial lines until the next write so padding occurs only at the end.
        for offset in range(0, len(data), BUFFER_SIZE):
            chunk = self.pending + data[offset:offset + BUFFER_SIZE]
            complete = len(chunk) // 57 * 57
            if complete:
                self.destination.write(base64.encodebytes(chunk[:complete]))
            self.pending = chunk[complete:]
        return len(data)

    def finish(self) -> None:
        if self.pending:
            self.destination.write(base64.encodebytes(self.pending))
            self.pending = b""


class _Base64Reader:
    """Decode bounded text chunks, rejecting malformed or trailing content."""

    def __init__(self, source: BinaryIO):
        header = source.readline(len(TEXT_HEADER) + 1)
        if header not in (TEXT_HEADER, TEXT_HEADER.replace(b"\n", b"\r\n")):
            raise ValueError("Invalid text bundle header; expected TARXZ64/1")
        self.source = source
        self.pending = b""
        self.decoded = b""
        self.padded = False
        self.finished = False

    def read(self, size: int) -> bytes:
        if size <= 0:
            return b""
        while not self.decoded and not self.finished:
            chunk = self.source.read(64 * 1024)
            if not chunk:
                if self.pending:
                    raise ValueError("Incomplete Base64 data in text bundle")
                self.finished = True
                break
            # Accept ASCII whitespace, including LF and CRLF line wrapping.
            self.pending += b"".join(chunk.split())
            if self.padded and self.pending:
                raise ValueError("Unexpected data after Base64 padding")
            complete = len(self.pending) // 4 * 4
            if complete:
                encoded, self.pending = self.pending[:complete], self.pending[complete:]
                try:
                    self.decoded = base64.b64decode(encoded, validate=True)
                except binascii.Error as error:
                    raise ValueError(f"Invalid Base64 data in text bundle: {error}") from error
                self.padded = b"=" in encoded
                if self.padded and self.pending:
                    raise ValueError("Unexpected data after Base64 padding")
        result, self.decoded = self.decoded[:size], self.decoded[size:]
        return result


def _path_parts(name: str) -> list[str]:
    """Reject ambiguous paths before either writing or reading an archive."""
    parts = name.split("/")
    if (
        not name
        or "\\" in name
        or ":" in name
        or "\0" in name
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise ValueError(f"Unsafe archive path: {name!r}")
    if os.name == "nt":
        for part in parts:
            stem = part.split(".")[0].upper()
            reserved = stem in {"CON", "PRN", "AUX", "NUL"} or (
                len(stem) == 4
                and stem[:3] in {"COM", "LPT"}
                and stem[3] in "123456789\u00b9\u00b2\u00b3"
            )
            if (
                reserved
                or part.endswith((".", " "))
                or any(ord(char) < 32 or char in '<>"|?*' for char in part)
            ):
                raise ValueError(f"Path cannot be restored on Windows: {name!r}")
    return parts


def _check_source_path(path: Path, source: Path) -> None:
    # Check ancestors too: a tracked directory may have been replaced by a link.
    current = path
    while current != source:
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or current.is_junction():
            raise ValueError(f"Links are not supported: {current}")
        if current == path and not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Expected a regular file: {path}")
        current = current.parent


def _select_files(source: Path, output: Path, all_files: bool, tracked_only: bool) -> list[Path]:
    if tracked_only:
        result = subprocess.run(
            ["git", "-C", str(source), "ls-files", "-z", "--", "."],
            check=True,
            capture_output=True,
        )
        names = {os.fsdecode(name) for name in result.stdout.split(b"\0") if name}
        candidates = [source.joinpath(*_path_parts(name)) for name in names]
    else:
        candidates = []

        def fail(error: OSError) -> None:
            raise error

        for directory, folders, files in os.walk(source, onerror=fail, followlinks=False):
            for folder in folders:
                path = Path(directory) / folder
                if path.is_symlink() or path.is_junction():
                    raise ValueError(f"Links are not supported: {path}")
            candidates.extend(Path(directory) / name for name in files)

    selected = []
    known_paths: dict[str, str] = {}
    for path in candidates:
        if path == output or (not all_files and path.suffix.lower() != ".py"):
            continue
        _claim_path(path.relative_to(source).as_posix(), known_paths)
        _check_source_path(path, source)
        selected.append(path)
    return sorted(selected, key=lambda path: path.relative_to(source).as_posix())


def pack_folder(
    source_folder: Path,
    output_file: Path,
    *,
    all_files: bool = False,
    tracked_only: bool = False,
) -> BundleStats:
    """Create a deterministic text bundle, replacing the output only on success."""
    source = source_folder.resolve()
    output = output_file.absolute()
    output = output.parent.resolve() / output.name
    if output.suffix.lower() != ".txt":
        raise ValueError("Output file must have a .txt extension")
    if not source.is_dir():
        raise NotADirectoryError(f"Source folder does not exist: {source}")
    if output.is_symlink() or output.is_junction():
        raise ValueError(f"Output must not be a link: {output}")
    selected = _select_files(source, output, all_files, tracked_only)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    temporary = Path(temporary_name)
    content_bytes = 0
    try:
        with os.fdopen(descriptor, "wb") as destination:
            encoded = _Base64Writer(destination)
            with tarfile.open(
                fileobj=encoded,
                mode="w:xz",
                format=tarfile.PAX_FORMAT,
                preset=COMPRESSION_PRESET,
            ) as archive:
                for path in selected:
                    _check_source_path(path, source)
                    with path.open("rb") as data:
                        before = os.fstat(data.fileno())
                        member = tarfile.TarInfo(path.relative_to(source).as_posix())
                        member.size = before.st_size
                        # TarInfo's fixed defaults omit original filesystem metadata.
                        archive.addfile(member, data)
                        after = os.fstat(data.fileno())
                        if (
                            data.read(1)
                            or before.st_size != after.st_size
                            or before.st_mtime_ns != after.st_mtime_ns
                        ):
                            raise ValueError(f"Source changed while packing: {path}")
                        content_bytes += member.size
            encoded.finish()
        archive_bytes = temporary.stat().st_size
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return BundleStats(len(selected), content_bytes, archive_bytes)


class _XZReader:
    """Bounded streaming decoder that requires a complete, checked XZ stream."""

    def __init__(self, source: _Base64Reader):
        self.source = source
        self.decoder = lzma.LZMADecompressor(
            format=lzma.FORMAT_XZ, memlimit=256 * 1024 * 1024
        )
        self.finished = False

    def read(self, size: int) -> bytes:
        if size <= 0:
            return b""
        while not self.finished:
            data = b""
            if self.decoder.needs_input:
                data = self.source.read(BUFFER_SIZE)
                if not data:
                    raise ValueError("Truncated XZ stream")
            result = self.decoder.decompress(data, max_length=size)
            if self.decoder.eof:
                if self.decoder.check == lzma.CHECK_NONE:
                    raise ValueError("XZ archive has no integrity check")
                # Permit standard XZ zero padding, but no hidden second archive.
                padding = self.decoder.unused_data or self.source.read(BUFFER_SIZE)
                padding_size = 0
                while padding:
                    if any(padding):
                        raise ValueError("Unexpected data after the XZ stream")
                    padding_size += len(padding)
                    padding = self.source.read(BUFFER_SIZE)
                if padding_size % 4:
                    raise ValueError("Invalid XZ stream padding")
                self.finished = True
            if result or self.finished:
                return result
        return b""


class _StrictTarInfo(tarfile.TarInfo):
    @classmethod
    def frombuf(cls, buf: bytes, encoding: str, errors: str) -> "_StrictTarInfo":
        try:
            member = super().frombuf(buf, encoding, errors)
        except tarfile.EOFHeaderError:
            raise
        except tarfile.HeaderError as error:
            # TarFile.next otherwise treats several malformed later headers as EOF.
            raise tarfile.ReadError(f"Invalid TAR header: {error}") from error
        if member.size < 0:
            raise ValueError(f"Negative file size: {member.name!r}")
        if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.XHDTYPE):
            raise ValueError(f"Unsupported archive entry: {member.name!r}")
        if member.type == tarfile.XHDTYPE and member.size > BUFFER_SIZE:
            raise ValueError("TAR path metadata is too large")
        return member


def _claim_path(name: str, known_paths: dict[str, str]) -> list[str]:
    parts = _path_parts(name)
    for index in range(1, len(parts) + 1):
        prefix = "/".join(parts[:index])
        key = os.path.normcase(prefix)
        previous = known_paths.get(key)
        if previous is not None and (previous != prefix or index == len(parts)):
            raise ValueError(f"Duplicate or conflicting archive path: {name!r}")
        known_paths[key] = prefix
    return parts


def unpack_bundle(bundle_file: Path, output_folder: Path) -> BundleStats:
    """Restore regular files to a new directory; publish only after validation."""
    output = output_folder.absolute()
    output = output.parent.resolve() / output.name
    if os.path.lexists(output):
        raise FileExistsError(f"Output folder already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    file_count = content_bytes = 0
    known_paths: dict[str, str] = {}
    with bundle_file.open("rb") as source:
        archive_bytes = os.fstat(source.fileno()).st_size
        with tempfile.TemporaryDirectory(prefix=f".{output.name}.", dir=output.parent) as temporary:
            staging = Path(temporary) / "files"
            staging.mkdir()
            reader = _XZReader(_Base64Reader(source))
            with tarfile.open(
                fileobj=reader, mode="r|", tarinfo=_StrictTarInfo, bufsize=64 * 1024
            ) as archive:
                for member in archive:
                    if not member.isreg() or member.issparse() or member.size < 0:
                        raise ValueError(f"Unsupported archive entry: {member.name!r}")
                    parts = _claim_path(member.name, known_paths)
                    target = staging.joinpath(*parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    data = archive.extractfile(member)
                    if data is None:
                        raise ValueError(f"Missing file data: {member.name!r}")
                    with data, target.open("xb") as destination:
                        shutil.copyfileobj(data, destination, length=BUFFER_SIZE)
                        if destination.tell() != member.size:
                            raise ValueError(f"Incomplete file: {member.name!r}")
                    file_count += 1
                    content_bytes += member.size
                # Iteration stops at the first zero TAR block. Consume the
                # buffered remainder too, requiring the second terminator block
                # and checking XZ's checksum/trailer before publishing any files.
                padding_size = 0
                while padding := archive.fileobj.read(BUFFER_SIZE):
                    if any(padding):
                        raise ValueError("Unexpected data after the TAR terminator")
                    padding_size += len(padding)
                if padding_size < tarfile.BLOCKSIZE or padding_size % tarfile.BLOCKSIZE:
                    raise ValueError("Incomplete TAR terminator")
            if os.path.lexists(output):
                raise FileExistsError(f"Output folder already exists: {output}")
            staging.rename(output)
    return BundleStats(file_count, content_bytes, archive_bytes)
