from pathlib import Path
import argparse
import base64
import hashlib
import json
import subprocess
import zlib


MAGIC = "PYBUNDLE1"
PROJECT_MAGIC = "FILEBUNDLE1"
COMPRESSED_MAGIC = "ZBUNDLE1"


def pack_folder(
    source_folder: Path,
    output_file: Path,
    *,
    all_files: bool = False,
    tracked_only: bool = False,
    compress: bool = True,
) -> None:
    source_folder = source_folder.resolve()
    output_file = output_file.resolve()

    if tracked_only:
        result = subprocess.run(
            ["git", "-C", str(source_folder), "ls-files", "-z", "--", "."],
            check=True,
            capture_output=True,
        )
        selected_files = [
            source_folder / name
            for name in result.stdout.decode("utf-8").split("\0")
            if name and (all_files or name.lower().endswith(".py"))
        ]
        for file_path in selected_files:
            if not file_path.is_file():
                raise FileNotFoundError(f"Tracked file is missing: {file_path}")
    else:
        pattern = "*" if all_files else "*.py"
        selected_files = [path for path in source_folder.rglob(pattern) if path.is_file()]

    records = []

    for file_path in sorted(selected_files):
        # Avoid accidentally packing the output if it happens to be .py
        if file_path.resolve() == output_file:
            continue

        relative_path = file_path.relative_to(source_folder)

        # Read raw bytes so encoding/newlines are preserved exactly
        content = file_path.read_bytes()

        records.append({
            "path": relative_path.as_posix(),
            "content": base64.b64encode(content).decode("ascii"),
        })

    bundle = {
        "format": PROJECT_MAGIC if all_files else MAGIC,
        "file_count": len(records),
        "files": records,
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)

    if compress:
        payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        bundle = {
            "format": COMPRESSED_MAGIC,
            "compression": "zlib",
            "encoding": "base64",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "data": base64.b64encode(zlib.compress(payload, level=9)).decode("ascii"),
        }

    output_file.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    label = "project files" if all_files else "Python files"
    print(f"Packed {len(records)} {label}")
    print(f"Source: {source_folder}")
    print(f"Output: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Combine Python files or a complete project into a compressed text bundle."
    )

    parser.add_argument(
        "source",
        type=Path,
        help="Source project folder",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("python_bundle.txt"),
        help="Output TXT file",
    )

    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Include every file type, including dashboard assets and project metadata",
    )
    parser.add_argument(
        "--no-compress",
        action="store_true",
        help="Write the legacy uncompressed JSON format instead of compressed text",
    )
    parser.add_argument(
        "--tracked-only",
        action="store_true",
        help="Include only Git-tracked files under the source folder (requires Git)",
    )

    args = parser.parse_args()

    if not args.source.is_dir():
        raise SystemExit(f"Folder does not exist: {args.source}")

    pack_folder(
        args.source,
        args.output,
        all_files=args.all_files,
        tracked_only=args.tracked_only,
        compress=not args.no_compress,
    )


if __name__ == "__main__":
    main()
