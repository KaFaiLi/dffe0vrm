# Lossless compressed text bundles

`pack.py` compresses file paths and original bytes with TAR/XZ, then encodes the
compressed bytes as ASCII text in a `.txt` file. `unpack.py` decodes and restores
those files directly into a new folder, without a separate archive-conversion step.
Requires **Python 3.12 or newer**, with the standard-library `lzma` module.
There are no third-party dependencies. Git is required only for `--tracked-only`.

## Pack and restore

```powershell
# Python files only, including uppercase .PY extensions:
python pack.py ./project -o python_bundle.txt

# All file types tracked by Git under this folder:
python pack.py ./project --all-files --tracked-only -o project.txt

# Restore directly into a folder that does not yet exist:
python unpack.py project.txt -o ./restored_project
```

The default output is `python_bundle.txt`; output filenames must have a `.txt`
extension. The default restore folder is `restored_project`. Both commands report
the file count and byte totals, including the final text bundle size.

Without `--tracked-only`, packing walks the source folder recursively and does
not apply Git ignore rules. `--all-files` includes every regular file type.
Tracked exports read the current working-tree bytes, including unstaged edits;
they fail if a selected tracked file is missing. The output archive is excluded
when it is inside the source folder.

## Preservation and failure behavior

- File contents are read and written as bytes. Binary data, encodings, line
  endings, empty files, and nested relative paths are preserved.
- Original timestamps, permissions, ownership, and empty directories are not
  stored. Symlinks, directory junctions, and special files are rejected.
- Packing uses a stable path order and fixed TAR metadata. XZ preset 6 compresses
  the whole archive, allowing repetition across files to compress together.
- Base64 encoding happens after compression, producing printable ASCII text.
  Encoding and decoding stream in bounded chunks. Both LF and CRLF line endings
  are accepted when restoring a text bundle.
- Archive creation uses a temporary file beside the destination. An existing
  archive is replaced only after the new archive has been written successfully.
- Restoration uses a temporary directory beside the destination. The destination
  must not exist, even as an empty folder. Files are published only after every
  entry, the TAR terminator, the complete XZ integrity check, and the text
  envelope are validated.
  On failure, temporary output is cleaned up.
- Extraction rejects unsafe paths, duplicate or conflicting destinations,
  links, special entries, malformed headers, unchecked XZ streams, and
  invalid Base64, and truncated or corrupt bundles. Paths must be relative, without backslashes,
  colons, or empty/`.`/`..` components; Windows also rejects names it cannot
  represent safely.
- File contents stream in bounded chunks. Memory also includes the compression
  dictionary and the list of selected paths. Extraction limits the XZ decoder
  to 256 MiB and individual extended TAR headers to 1 MiB.

## Text format

Each bundle starts with the line `TARXZ64/1`, followed by standard Base64 data
wrapped at 76 characters per line. Decoding that data produces one checked XZ
stream containing a standard TAR archive. The `.txt` file is ASCII and therefore
also valid UTF-8. The source files themselves may contain arbitrary binary bytes.

`unpack.py` performs both decoding and extraction in one command. It accepts only
regular-file entries and PAX path headers, as produced by this packer. The former
JSON bundles and raw binary `.tar.xz` inputs are not supported.

## Included bundles

| Bundle | Contents | Files | Bundle bytes | Previous text bytes | Reduction |
| --- | --- | ---: | ---: | ---: | ---: |
| `python_bundle.txt` | GenAI manager, wrapper, and test snapshot | 83 | 158,659 | 919,116 | 82.74% |
| `data_package_agent_bundle.txt` | Complete Data Package Agent snapshot | 257 | 665,566 | 1,264,959 | 47.38% |

The Python baseline is the original uncompressed JSON bundle. The agent baseline
is the latest zlib/Base64 text bundle from the remote repository.

Both snapshots were converted without changing their relative paths or file
contents. All **340 files** were restored and compared by path and SHA-256
against the preceding binary archives (already verified against their original
records). These comparisons verify file contents; no
original filesystem metadata was available or required.

The agent export comes from
[`KaFaiLi/private_suite`, commit `ddee7f5`](https://github.com/KaFaiLi/private_suite/tree/ddee7f5/packages/data-package-agent),
as recorded by the remote snapshot refresh commit `7882227`.
It includes 161 Python files, all 59 files under `tests/`, all 20 files under
`dashboard/`, all 21 files under `docs/review/`, package documentation, scripts,
and project configuration. The application skills under `skills/` include
`market-activity-review`, `pnl`, `post-trade-control`, and `risk-metrics`;
all four `SKILL.md` files and their nine reference Markdown files are preserved.
Local environments, caches, build outputs, credentials, and SQLite recordings
are outside this Git-tracked snapshot.

```powershell
python unpack.py data_package_agent_bundle.txt -o data-package-agent

# Refresh from the suite checkout:
python pack.py 'P:/Alan/Github/private_suite/packages/data-package-agent' --all-files --tracked-only -o data_package_agent_bundle.txt
```

The restored agent keeps its corporate dependency configuration. With those
dependencies available:

```powershell
Set-Location data-package-agent
uv sync --extra dev
uv run pytest tests dashboard/tests -q
```

The dashboard itself needs only Python and an existing recording:

```powershell
python dashboard/server.py --db 'P:/path/to/observability.sqlite3'
```

The default URL is `http://127.0.0.1:8765`. The viewer reads SQLite without
changing it. See the restored `dashboard/README.md` for details.

## Development and validation

```powershell
python -m unittest discover -s tests -v
```

The suite covers byte-exact round trips, binary and Unicode data, long paths,
empty files, Python/Git selection, deterministic output, source changes,
failed writes, output exclusion, malformed archives and text envelopes, unsafe
paths, collisions, and refusal to overwrite an existing restore directory. Text
tests verify ASCII output, LF/CRLF handling, and restoration of a 2 MiB
incompressible file across encoding/decoding chunk boundaries.

On this Windows workstation with Python 3.13.7, conversion measured 0.23 / 0.80
seconds to pack and 0.07 / 0.24 seconds to restore the Python / agent snapshots
respectively, including filesystem I/O. These are single-run
measurements, not performance guarantees. A separate 32 MiB file restored with
a matching SHA-256 and a peak of 12.3 MiB measured by `tracemalloc`; this measures
traced allocations, not total process memory.

The newest remote snapshot was preserved during integration and verified against
all 257 decoded source records. Application tests and corporate dependency
installation were not run for this archive-format change.
