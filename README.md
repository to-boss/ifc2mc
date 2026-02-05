# ifc2mc

IFC to Minecraft importer.

## Tooling

- Use `uv` for dependency and environment management.
- Do not use `pip`.

## Quick Start

```bash
uv sync
uv run ifc2mc --help
uv run pytest
uv run ifc2mc import --ifc path/to/model.ifc --world path/to/world --dry-run
uv run ifc2mc import --ifc path/to/model.ifc --world path/to/world --dry-run --voxelize
uv run ifc2mc import --ifc path/to/model.ifc --world path/to/world --dry-run --block-map IfcWall=minecraft:stone_bricks --block-map IfcSlab=minecraft:smooth_stone
uv run ifc2mc import --ifc path/to/model.ifc --world path/to/world --dry-run --block-map material:wood=minecraft:spruce_planks --block-map IfcRailing|wood=minecraft:spruce_fence
uv run ifc2mc import --ifc path/to/model.ifc --world path/to/world --dry-run --block-map material_name:wood-generic=minecraft:dark_oak_planks
uv run ifc2mc import --ifc path/to/model.ifc --world path/to/world --dry-run --type-priority IfcWall=95 --type-priority IfcBeam=80
uv run ifc2mc import --ifc path/to/model.ifc --world /path/to/existing/minecraft/world
uv run ifc2mc import --ifc path/to/model.ifc --world /path/to/world --voxelize --yaw-deg 90
uv run ifc2mc import --ifc path/to/model.ifc --world /path/to/world --voxelize --snap-to-superflat --superflat-ground-y -60 --ground-clearance 1
```

Notes:
- Non-`--dry-run` mode writes blocks into an existing world directory using Amulet.
- If `--voxelize` is omitted in write mode, voxelization is enabled automatically.
- Default mapping is material-aware (e.g., wood, metal, concrete) and falls back to IFC type mappings when material data is missing.
- You can target exact IFC material names with `material_name:<name>` keys in `--block-map` overrides.
- Use `--clear-default-block-map` with one or more `--block-map IFCType=block_id` flags to fully control block assignment.
- Overlapping voxel candidates are resolved deterministically using IFC type priority defaults in `ifc2mc/config.py`.
- Use `--clear-default-type-priority` with one or more `--type-priority IFCType=priority` flags to fully control overlap precedence.
- Write mode reports `touched_chunks` to help estimate world-edit footprint.
- Runs report `timing_summary_ms` for open/validate, geometry scan, voxelization, write, and total runtime.
