# IFC to Minecraft Import Plan

## Goal
Create a pipeline that imports an IFC model into a Minecraft world, starting with:

- `https://github.com/buildingSMART/Sample-Test-Files/blob/main/IFC%204.3.2.0%20(IFC4X3_ADD2)/PCERT-Sample-Scene/Infra-Bridge.ifc`

## Recommended Stack
1. `IfcOpenShell` for IFC parsing and geometry extraction.
2. `trimesh` for mesh processing and voxelization.
3. `Amulet-Core` for writing blocks into Minecraft world data.

## Tooling Constraint
1. Use `uv` for all environment and dependency management.
2. Do not use `pip` directly.
3. Standard commands:
- `uv sync` to create/update the environment from `pyproject.toml`.
- `uv add <package>` to add dependencies.
- `uv run <command>` to run scripts and tools.

## Sample File Implications
1. Schema is `IFC4X3_ADD2`.
2. Length unit is millimeters (`IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.)`), so convert to meters before block scaling.
3. File includes georeferencing (`IfcMapConversion`) with very large offsets; recenter to local coordinates before writing to Minecraft.
4. Model already includes many triangulated face sets, which is favorable for voxelization workflows.

## Architecture
1. IFC ingest layer
- Stream geometry using `ifcopenshell.geom.iterator(...)`.
- Apply element transform matrices.
- Convert project units to meters with `ifcopenshell.util.unit.calculate_unit_scale(...)`.

2. Normalization layer
- Recenter coordinates around chosen anchor (center, min-corner, or fixed world origin).
- Apply orientation and axis convention rules once, centrally.
- Persist intermediate mesh/metadata for repeatable runs.

3. Voxelization layer
- Build `trimesh.Trimesh` objects from IFC triangles.
- Voxelize with `trimesh.voxel.creation.voxelize(mesh, pitch=...)`.
- Merge voxel sets and resolve overlaps by type priority.

4. Block mapping layer
- Map IFC class/material/style to Minecraft block states.
- Keep mappings in a Python config class (for example `dataclass` definitions in `config.py`).
- Start with coarse defaults, then refine by type/material.

5. Minecraft write layer
- Open world with `amulet.load_level(...)`.
- For MVP, place via `set_version_block(...)`.
- For performance, batch via chunk/palette writes and mark changed chunks.
- Save and close world cleanly.

## Implementation Phases
1. Phase 1: IFC to normalized mesh
- Read IFC and extract all relevant geometry.
- Output mesh stats and bounding box.
- Validate unit conversion and recentering.

2. Phase 2: Mesh to voxel grid
- Run voxelization at configurable pitch.
- Export preview artifacts (counts, bbox in blocks, optional debug slices).
- Tune pitch and fill/cleanup behavior.

3. Phase 3: Voxel grid to Minecraft world
- Map voxel classes to block types.
- Write into a test world at configurable origin and Y offset.
- Validate in-game alignment and continuity.

4. Phase 4: Hardening
- Add CLI (`ifc2mc import ...`) and Python class-based config profiles.
- Add include/exclude filters by IFC type.
- Improve performance and memory behavior for larger models.

## Python Config Approach
1. Use a typed Python class as the single source of configuration truth.
- Example pattern: `@dataclass class ImportConfig: ...`
- Include scale, origin policy, pitch, block mappings, include/exclude IFC types, and target world version.

2. Keep named presets as Python subclasses or factory functions.
- Example: `BridgePresetConfig(ImportConfig)` or `make_bridge_preset()`.

3. Avoid YAML/JSON config files for runtime configuration.
- Configuration changes are made in Python code and version-controlled with the importer.

## Milestones
1. `M1` (1-2 days): IFC geometry extraction + normalization + reporting.
2. `M2` (1-2 days): Voxelization pipeline with deterministic output.
3. `M3` (1 day): Minecraft world writing end-to-end.
4. `M4` (ongoing): fidelity improvements, mappings, and optimization.

## Key Decisions to Lock Early
1. Minecraft target: Java or Bedrock (recommend Java first).
2. Scale: meters-to-block ratio (example: `1 block = 0.5 m`).
3. Placement strategy: centered vs fixed world coordinates.
4. Fidelity target: fully solidized vs shell-only structures.

## Risks and Mitigations
1. Huge coordinates/georeferencing distort placement.
- Mitigation: recenter and operate in local engineering coordinates.

2. Thin elements disappear during voxelization.
- Mitigation: add minimum thickness policy or lower pitch.

3. Runtime and memory grow rapidly at fine pitch.
- Mitigation: chunked processing and configurable detail profiles.

4. Material semantics vary by authoring tool.
- Mitigation: start with class-based mapping and optional style overrides.

## Deliverables
1. CLI tool to import IFC into a chosen world.
2. Python config module with typed classes for IFC-to-block translation and import parameters.
3. Validation report (units, bbox, voxel count, placed chunks, dropped elements).
4. Reproducible test using `Infra-Bridge.ifc`.
