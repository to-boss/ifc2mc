# Repository Guidelines

## Project Structure & Module Organization
- `ifc2mc/` contains the application code:
- `ifc2mc/cli.py`: argparse entrypoint for `ifc2mc import`.
- `ifc2mc/importer.py`: IFC parsing, geometry transforms, voxelization, and world write flow.
- `ifc2mc/config.py`: typed `ImportConfig` and default IFC-to-block mapping.
- `main.py` is a thin local launcher that calls `ifc2mc.cli:main`.
- `README.md` documents usage; keep it updated when CLI flags or behavior change.
- `plan.md` captures architecture/phase intent; align major refactors with it.

## Build, Test, and Development Commands
- `uv sync`: install/update dependencies and environment from `pyproject.toml` + `uv.lock`.
- `uv run ifc2mc --help`: verify CLI wiring and available commands.
- `uv run ifc2mc import --ifc path/to/model.ifc --world path/to/world --dry-run`: safe validation run (no writes).
- `uv run ifc2mc import --ifc path/to/model.ifc --world path/to/world --voxelize`: full import path including voxelization.
- No separate build pipeline is required today; package execution is via `uv run`.

## Coding Style & Naming Conventions
- Target Python `>=3.13`; use type hints on public functions and dataclass fields.
- Follow PEP 8 with 4-space indentation and `snake_case` for functions/variables.
- Use `PascalCase` for dataclasses (`ImportConfig`, `VoxelizationSummary`) and `UPPER_SNAKE_CASE` for constants.
- Keep functions focused and side effects explicit, especially in import/write steps.

## Testing Guidelines
- A formal test suite is not committed yet. Add tests under `tests/` as `test_*.py`.
- Prefer `pytest` style assertions and deterministic fixtures for geometry transforms and placement math.
- For importer changes, include at least one dry-run regression test (bbox/chunk range/voxel counts).
- Run tests with `uv run pytest` once tests are present.

## Commit & Pull Request Guidelines
- Match current commit style: short, imperative, capitalized subject (e.g., `Fix IFC axis mapping...`).
- Keep commits focused by concern (CLI flags, placement math, voxelization behavior, docs).
- PRs should include what changed and why, plus exact validation commands.
- Include dry-run/import output snippets when behavior changes.
- Link the related issue or task when applicable.

## Safety & Configuration Tips
- Prefer `--dry-run` before any write operation; non-dry runs modify world data.
- Use a copy of a Minecraft world for development imports to avoid accidental corruption.
- Keep default block mappings in `ifc2mc/config.py` conservative, then iterate by IFC type.
