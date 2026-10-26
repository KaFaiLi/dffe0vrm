"""Restore a binary source archive directly into a new folder."""

import argparse
import lzma
from pathlib import Path
import tarfile

from bundle import unpack_bundle


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore original file paths and bytes from a .tar.xz archive."
    )
    parser.add_argument("bundle", type=Path, help="Archive created by pack.py")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("restored_project"),
        help="New output folder; must not already exist (default: restored_project)",
    )
    args = parser.parse_args()
    try:
        stats = unpack_bundle(args.bundle, args.output)
    except (OSError, ValueError, EOFError, tarfile.TarError, lzma.LZMAError) as error:
        parser.exit(1, f"Restoration failed: {error}\n")
    print(f"Restored {stats.file_count} files ({stats.content_bytes:,} bytes)")
    print(f"Output: {args.output.resolve()}")


if __name__ == "__main__":
    main()
