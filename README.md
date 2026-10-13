# Source text bundles

This private repository stores JSON text bundles with Base64-encoded file bytes.
`pack.py` creates them and `unpack.py` restores the original paths and contents.

| Bundle | Contents | Format |
| --- | --- | --- |
| `python_bundle.txt` | Existing GenAI manager, wrapper, and test snapshot; 83 Python files | `PYBUNDLE1` |
| `data_package_agent_bundle.txt` | Complete Data Package Agent project; 97 tracked files, including 80 Python files | `FILEBUNDLE1` |

The agent export comes from
[`KaFaiLi/private_suite`, commit `40360ed`](https://github.com/KaFaiLi/private_suite/tree/40360ed966967fe292105ac4578fdff5228c6864/packages/data-package-agent).
It includes `src/`, all 18 files under `tests/`, all 16 files under `dashboard/`
(including its tests, HTML, JavaScript, CSS, and SVG), package documentation,
scripts, `pyproject.toml`, Python selection, and contributor/ignore files.
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

`--all-files` selects `FILEBUNDLE1` and includes frontend assets and project
metadata. `--tracked-only` selects only files tracked by Git under the source
folder, so ignored local state is excluded. This option requires Git.

Without `--all-files`, the existing Python-only `PYBUNDLE1` behavior is preserved.
The updated unpacker supports both formats and retains its path containment check.

## Export validation

The complete export was restored and all 97 files were compared byte-for-byte
against the source and their decoded bundle records. Compatibility checks also
verified the Python-only default, binary and CRLF preservation, rejection of
unsafe paths in both formats, and restoration of the existing 83-file GenAI bundle.
The restored dashboard JavaScript passed syntax checks.

The restored agent and dashboard suite passed all 149 tests in 36.80 seconds
using the previously available local dependency cache. Corporate installation
remains unavailable on this workstation; cached FastMCP 4.0.10 and langchain-core
1.6.5 are below the project's
declared minimums. The source requirements are preserved. Repeat the normal
installation and combined tests after corporate dependency access is restored.
