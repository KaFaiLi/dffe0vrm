# Source text bundles

This private repository stores JSON text bundles with Base64-encoded file bytes.
`pack.py` creates them and `unpack.py` restores the original paths and contents.

| Bundle | Contents | Format |
| --- | --- | --- |
| `python_bundle.txt` | Existing GenAI manager, wrapper, and test snapshot; 83 Python files | `PYBUNDLE1` |
| `data_package_agent_bundle.txt` | Complete Data Package Agent project; 190 tracked files, including 144 Python files and 12 bundled skill Markdown files | `FILEBUNDLE1` |

The agent export comes from
[`KaFaiLi/private_suite`, commit `8406f9d`](https://github.com/KaFaiLi/private_suite/tree/8406f9d55a30e18dcc5e20005480cbaad75394f4/packages/data-package-agent).
It includes `src/`, all 42 files under `tests/`, all 19 files under `dashboard/`
(including its tests, HTML, JavaScript, CSS, and SVG), package documentation,
scripts, `pyproject.toml`, Python selection, and contributor/ignore files.
The bundled skills under `src/mcp_agent_template/_bundled_skills/` include
`pnl`, `post-trade-controls`, `risk-commentary`, and `risk-metrics`: each has
its `SKILL.md` and both reference Markdown files (`dataset.md` and `policy.md`).
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

The refreshed export was restored with `unpack.py`. All 190 paths matched the
source project's Git-tracked file list, and every restored file was compared
byte-for-byte against both its source and decoded bundle record. All four
`SKILL.md` files and their eight reference Markdown files were verified included.

This refresh validates export completeness and restoration. Application tests
and corporate dependency installation were not run for this source snapshot.
