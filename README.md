# Source text bundles

This private repository stores compressed text bundles. `pack.py` compresses
the file records with zlib and encodes the result as Base64 inside a JSON text
file. `unpack.py` verifies the SHA-256 checksum and restores the original paths
and bytes. Both scripts use only the Python standard library.

| Bundle | Contents | Format |
| --- | --- | --- |
| `python_bundle.txt` | Existing GenAI manager, wrapper, and test snapshot; 83 Python files | `PYBUNDLE1` |
| `data_package_agent_bundle.txt` | Complete Data Package Agent project; 215 tracked files, including 155 Python files and 12 skill Markdown files | `ZBUNDLE1` (compressed `FILEBUNDLE1`) |

The agent export comes from
[`KaFaiLi/private_suite`, commit `e85767e`](https://github.com/KaFaiLi/private_suite/tree/e85767e593d4bd169ed9639c3e49142648d5df49/packages/data-package-agent).
It includes `src/`, all 52 files under `tests/`, all 20 files under `dashboard/`
(including its five test files, HTML, JavaScript, CSS, and SVG), package documentation,
scripts, `pyproject.toml`, Python selection, and contributor/ignore files.
All 14 files under `docs/review/` are included.
The application skills under `skills/` include `market-activity-review`, `pnl`,
`post-trade-control`, and `risk-metrics`. All four `SKILL.md` files and their eight
reference Markdown files are included in their original folder structure.
Local environments, caches, build outputs, credentials, and SQLite recordings
are outside the exported Git-tracked project.

## Restore the complete agent

```powershell
python unpack.py data_package_agent_bundle.txt -o data-package-agent
```

The restored folder keeps the project's existing structure and corporate
dependency configuration. With the corporate dependencies available, run:

```powershell
Set-Location data-package-agent
uv sync --extra dev
uv run pytest tests dashboard/tests -q
```

The dashboard itself needs only Python. Supply an existing recording when
launching it; databases are not included in the source bundle:

```powershell
python dashboard/server.py --db 'P:/path/to/observability.sqlite3'
```

The default URL is `http://127.0.0.1:8765`. The viewer reads SQLite without
changing it. Its full instructions are in the restored `dashboard/README.md`.

## Refresh the agent bundle

From this repository, using the current suite checkout:

```powershell
python pack.py 'P:/Alan/Github/private_suite/packages/data-package-agent' --all-files --tracked-only -o data_package_agent_bundle.txt
```

`--all-files` includes frontend assets, skill Markdown files and project
metadata. `--tracked-only` selects only files tracked by Git under the source
folder, so ignored local state is excluded. This option requires Git.

Without `--all-files`, only Python files are included. Compression is enabled by
default for both selections. Add `--no-compress` to write legacy JSON instead:

```powershell
python pack.py 'P:/Alan/Github/private_suite/packages/data-package-agent' --all-files --tracked-only --no-compress -o uncompressed_agent.txt
```

## Compression and compatibility

`ZBUNDLE1` is a JSON envelope with `compression: "zlib"`, `encoding: "base64"`,
`sha256` (the decompressed JSON's SHA-256), and `data` (the compressed bytes as
Base64). The decompressed JSON retains the existing `PYBUNDLE1` or `FILEBUNDLE1`
records, preserving binary files, text encoding and line endings. Output is
deterministic for the same inputs and compression runtime.

The unpacker detects all three formats automatically, so restore commands do
not change. Use the updated `unpack.py` for compressed bundles; older unpackers
need bundles created with `--no-compress`. Invalid compressed data or a checksum
mismatch is rejected before restoration starts. The path containment check still
applies to both compressed and legacy bundles.

The current agent bundle is **1,061,881 bytes**, compared with **2,606,853 bytes**
for the same snapshot as legacy JSON: **59.3% smaller**.

## Export validation

The refreshed export was restored with `unpack.py`. All 215 paths matched the
source project's Git-tracked file list, and every restored file was compared
byte-for-byte against both its source and decoded bundle record. All four
`SKILL.md` files and their eight reference Markdown files were verified included.
Both previously committed legacy bundles also restored byte-for-byte.

Run the 10 standard-library regression tests with:

```powershell
python -B -m unittest -v
```

They cover compressed and legacy restoration, CLI options, binary/CRLF/Unicode
preservation, empty inputs, tracked file selection, output exclusion, deterministic
compression, corruption rejection and path containment.

This refresh validates export completeness and restoration. Application tests
and corporate dependency installation were not run for this source snapshot.
