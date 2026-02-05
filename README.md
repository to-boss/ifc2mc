# ifc2mc

IFC to Minecraft importer.

## Tooling

- Use `uv` for dependency and environment management.
- Do not use `pip`.

## Quick Start

```bash
uv sync
uv run ifc2mc --help
uv run ifc2mc import --ifc path/to/model.ifc --world path/to/world --dry-run
uv run ifc2mc import --ifc path/to/model.ifc --world path/to/world --dry-run --voxelize
```
