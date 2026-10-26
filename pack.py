"""Create a lossless binary source archive."""

import argparse
import lzma
from pathlib import Path
import subprocess
import tarfile

from bundle import pack_folder


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compress Python files or a complete project into a .tar.xz archive."
    )
    parser.add_argument("source", type=Path, help="Source project folder")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("python_bundle.tar.xz"),
        help="Output archive (default: python_bundle.tar.xz)",
    )
    parser.add_argument(
        "--all-files", action="store_true", help="Include every regular file type",
    )
    parser.add_argument(
        "--tracked-only", action="store_true",
        help="Include only Git-tracked files under the source folder (requires Git)",
    )
    args = parser.parse_args()
    try:
        stats = pack_folder(
            args.source, args.output, all_files=args.all_files, tracked_only=args.tracked_only
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        parser.exit(1, f"Packing failed: {detail or str(error)}\n")
    except (OSError, ValueError, tarfile.TarError, lzma.LZMAError) as error:
        parser.exit(1, f"Packing failed: {error}\n")
    print(f"Packed {stats.file_count} files ({stats.content_bytes:,} source bytes)")
    print(f"Archive: {args.output.resolve()} ({stats.archive_bytes:,} bytes)")


if __name__ == "__main__":
    main()
