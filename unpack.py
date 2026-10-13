from pathlib import Path
import argparse
import base64
import json


MAGIC = "PYBUNDLE1"
PROJECT_MAGIC = "FILEBUNDLE1"


def safe_output_path(output_folder: Path, relative_path: str) -> Path:
    """
    Prevent paths such as ../../something.py from escaping
    the requested output directory.
    """
    output_folder = output_folder.resolve()
    target = (output_folder / relative_path).resolve()

    try:
        target.relative_to(output_folder)
    except ValueError:
        raise ValueError(
            f"Unsafe path found in bundle: {relative_path}"
        )

    return target


def unpack_bundle(bundle_file: Path, output_folder: Path) -> None:
    bundle = json.loads(
        bundle_file.read_text(encoding="utf-8")
    )

    if bundle.get("format") not in (MAGIC, PROJECT_MAGIC):
        raise ValueError(
            f"Invalid bundle format. Expected {MAGIC} or {PROJECT_MAGIC}."
        )

    output_folder.mkdir(parents=True, exist_ok=True)

    files = bundle.get("files", [])

    for record in files:
        relative_path = record["path"]

        if bundle["format"] == MAGIC and not relative_path.endswith(".py"):
            raise ValueError(
                f"Unexpected non-Python file: {relative_path}"
            )

        target = safe_output_path(
            output_folder,
            relative_path,
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        content = base64.b64decode(
            record["content"],
            validate=True,
        )

        target.write_bytes(content)

        print(f"Created: {relative_path}")

    print()
    label = "project files" if bundle["format"] == PROJECT_MAGIC else "Python files"
    print(f"Restored {len(files)} {label}")
    print(f"Output: {output_folder.resolve()}")


def main():
    parser = argparse.ArgumentParser(
        description="Restore files from a PYBUNDLE1 or FILEBUNDLE1 text bundle."
    )

    parser.add_argument(
        "bundle",
        type=Path,
        help="TXT bundle created by pack.py",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("restored_project"),
        help="Folder to restore files into",
    )

    args = parser.parse_args()

    if not args.bundle.is_file():
        raise SystemExit(
            f"Bundle does not exist: {args.bundle}"
        )

    unpack_bundle(args.bundle, args.output)


if __name__ == "__main__":
    main()
