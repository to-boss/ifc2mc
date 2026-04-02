# ifc2mc

Import IFC models into Minecraft Java Edition worlds.

## Requirements

- [uv](https://docs.astral.sh/uv/) for dependency management
- Minecraft **Java Edition 1.20.4** (the target world must be created in this version — newer versions are not supported by the Amulet library)

## Setup

```bash
uv sync
```

## Usage

```bash
# Dry run (no world changes, just a report)
uv run ifc2mc import --ifc model.ifc --world /path/to/world --dry-run --voxelize

# Write into a world (close Minecraft first!)
uv run ifc2mc import --ifc model.ifc --world /path/to/world --voxelize
```

On Windows, worlds are at `%APPDATA%\.minecraft\saves\<world name>`.

### Options

| Flag | Description |
|------|-------------|
| `--dry-run` | Report only, no blocks written |
| `--voxelize` | Enable voxelization (auto-enabled in write mode) |
| `--meters-per-block` | Scale (default: 0.5) |
| `--yaw-deg` | Rotate model in degrees |
| `--snap-to-superflat` | Align to superflat ground level |
| `--block-map TYPE=BLOCK` | Override block mapping (repeatable) |
| `--type-priority TYPE=N` | Override overlap priority (repeatable) |

Block map supports IFC type (`IfcWall=minecraft:stone_bricks`), material bucket (`material:wood=minecraft:spruce_planks`), and exact material name (`material_name:wood-generic=minecraft:dark_oak_planks`) keys.

Run `uv run ifc2mc import --help` for all options.

## Tests

```bash
uv run pytest
```
