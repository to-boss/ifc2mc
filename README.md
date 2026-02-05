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
uv run ifc2mc import --ifc path/to/model.ifc --world /path/to/existing/minecraft/world
uv run ifc2mc import --ifc path/to/model.ifc --world /path/to/world --voxelize --yaw-deg 90
uv run ifc2mc import --ifc path/to/model.ifc --world /path/to/world --voxelize --snap-to-superflat --superflat-ground-y -60 --ground-clearance 1
```

Notes:
- Non-`--dry-run` mode writes blocks into an existing world directory using Amulet.
- If `--voxelize` is omitted in write mode, voxelization is enabled automatically.
