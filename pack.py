from pathlib import Path
import argparse
import base64
import json


MAGIC = "PYBUNDLE1"


def pack_folder(source_folder: Path, output_file: Path) -> None:
    source_folder = source_folder.resolve()
    output_file = output_file.resolve()

    py_files = sorted(source_folder.rglob("*.py"))

    records = []

    for file_path in py_files:
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
        "format": MAGIC,
        "file_count": len(records),
        "files": records,
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)

    output_file.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Packed {len(records)} Python files")
    print(f"Source: {source_folder}")
    print(f"Output: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Combine all Python files in a folder into one text bundle."
    )

    parser.add_argument(
        "source",
        type=Path,
        help="Folder containing Python files",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("python_bundle.txt"),
        help="Output TXT file",
    )

    args = parser.parse_args()

    if not args.source.is_dir():
        raise SystemExit(f"Folder does not exist: {args.source}")

    pack_folder(args.source, args.output)


if __name__ == "__main__":
    main()