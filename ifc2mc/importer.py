from __future__ import annotations

import math
import multiprocessing
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.unit

from .config import ImportConfig


@dataclass(slots=True)
class GeometryScan:
    shape_count: int
    empty_shape_count: int
    bbox_min_proj: tuple[float, float, float] | None
    bbox_max_proj: tuple[float, float, float] | None


@dataclass(slots=True)
class PlacementPlan:
    bbox_min_blocks: tuple[float, float, float]
    bbox_max_blocks: tuple[float, float, float]
    bbox_min_blocks_int: tuple[int, int, int]
    bbox_max_blocks_int: tuple[int, int, int]
    chunk_min_x: int
    chunk_max_x: int
    chunk_min_z: int
    chunk_max_z: int


def _fmt_vec3(values: tuple[float, float, float], ndigits: int = 3) -> str:
    return f"({values[0]:.{ndigits}f}, {values[1]:.{ndigits}f}, {values[2]:.{ndigits}f})"


def _fmt_int3(values: tuple[int, int, int]) -> str:
    return f"({values[0]}, {values[1]}, {values[2]})"


def _validate_ifc_types(ifc_file: ifcopenshell.file, type_names: tuple[str, ...], *, label: str) -> None:
    invalid: list[str] = []
    for type_name in type_names:
        try:
            ifc_file.by_type(type_name)
        except RuntimeError:
            invalid.append(type_name)
    if invalid:
        invalid_list = ", ".join(sorted(invalid))
        raise ValueError(f"Unknown IFC {label} type(s): {invalid_list}")


def _collect_candidate_elements(
    ifc_file: ifcopenshell.file,
    include_types: tuple[str, ...],
    exclude_types: tuple[str, ...],
) -> list[Any]:
    if include_types:
        candidates: list[Any] = []
        for type_name in include_types:
            candidates.extend(ifc_file.by_type(type_name))
    else:
        candidates = list(ifc_file.by_type("IfcProduct"))

    unique_by_id: dict[int, Any] = {}
    for entity in candidates:
        entity_id = int(entity.id())
        unique_by_id.setdefault(entity_id, entity)

    selected = list(unique_by_id.values())
    if exclude_types:
        selected = [
            entity
            for entity in selected
            if not any(entity.is_a(excluded) for excluded in exclude_types)
        ]

    selected.sort(key=lambda entity: int(entity.id()))
    return selected


def _scan_geometry(
    ifc_file: ifcopenshell.file,
    entities: list[Any],
) -> GeometryScan:
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    # Keep geometry in SI units (meters) for simpler downstream math.
    settings.set("convert-back-units", False)

    iterator = ifcopenshell.geom.iterator(
        settings,
        ifc_file,
        max(1, multiprocessing.cpu_count()),
        include=entities,
    )
    if not iterator.initialize():
        return GeometryScan(
            shape_count=0,
            empty_shape_count=0,
            bbox_min_proj=None,
            bbox_max_proj=None,
        )

    shape_count = 0
    empty_shape_count = 0
    min_x = min_y = min_z = math.inf
    max_x = max_y = max_z = -math.inf

    while True:
        shape = iterator.get()
        shape_count += 1
        verts = shape.geometry.verts
        if not verts:
            empty_shape_count += 1
        else:
            for i in range(0, len(verts), 3):
                x = float(verts[i])
                y = float(verts[i + 1])
                z = float(verts[i + 2])
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if z < min_z:
                    min_z = z
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y
                if z > max_z:
                    max_z = z

        if not iterator.next():
            break

    if math.isinf(min_x):
        bbox_min = None
        bbox_max = None
    else:
        bbox_min = (min_x, min_y, min_z)
        bbox_max = (max_x, max_y, max_z)

    return GeometryScan(
        shape_count=shape_count,
        empty_shape_count=empty_shape_count,
        bbox_min_proj=bbox_min,
        bbox_max_proj=bbox_max,
    )


def _plan_block_placement(
    bbox_min_m: tuple[float, float, float],
    bbox_max_m: tuple[float, float, float],
    config: ImportConfig,
) -> PlacementPlan:
    min_x, min_y, min_z = bbox_min_m
    max_x, max_y, max_z = bbox_max_m

    if config.origin_mode == "centered":
        shift_x = -((min_x + max_x) / 2.0)
        shift_z = -((min_z + max_z) / 2.0)
        world_x_offset_blocks = 0.0
        world_z_offset_blocks = 0.0
    elif config.origin_mode == "min_corner":
        shift_x = -min_x
        shift_z = -min_z
        world_x_offset_blocks = 0.0
        world_z_offset_blocks = 0.0
    else:
        shift_x = 0.0
        shift_z = 0.0
        world_x_offset_blocks = float(config.fixed_origin_x)
        world_z_offset_blocks = float(config.fixed_origin_z)

    # Keep the structure on or above the configured Y offset.
    shift_y = -min_y

    meters_per_block = config.meters_per_block
    min_block_x = (min_x + shift_x) / meters_per_block + world_x_offset_blocks
    min_block_y = (min_y + shift_y) / meters_per_block + float(config.y_offset)
    min_block_z = (min_z + shift_z) / meters_per_block + world_z_offset_blocks

    max_block_x = (max_x + shift_x) / meters_per_block + world_x_offset_blocks
    max_block_y = (max_y + shift_y) / meters_per_block + float(config.y_offset)
    max_block_z = (max_z + shift_z) / meters_per_block + world_z_offset_blocks

    min_block_x_i = math.floor(min_block_x)
    min_block_y_i = math.floor(min_block_y)
    min_block_z_i = math.floor(min_block_z)

    max_block_x_i = max(min_block_x_i, math.ceil(max_block_x) - 1)
    max_block_y_i = max(min_block_y_i, math.ceil(max_block_y) - 1)
    max_block_z_i = max(min_block_z_i, math.ceil(max_block_z) - 1)

    chunk_min_x = math.floor(min_block_x_i / 16)
    chunk_max_x = math.floor(max_block_x_i / 16)
    chunk_min_z = math.floor(min_block_z_i / 16)
    chunk_max_z = math.floor(max_block_z_i / 16)

    return PlacementPlan(
        bbox_min_blocks=(min_block_x, min_block_y, min_block_z),
        bbox_max_blocks=(max_block_x, max_block_y, max_block_z),
        bbox_min_blocks_int=(min_block_x_i, min_block_y_i, min_block_z_i),
        bbox_max_blocks_int=(max_block_x_i, max_block_y_i, max_block_z_i),
        chunk_min_x=chunk_min_x,
        chunk_max_x=chunk_max_x,
        chunk_min_z=chunk_min_z,
        chunk_max_z=chunk_max_z,
    )


def run_import(config: ImportConfig, *, dry_run: bool = False) -> int:
    if config.meters_per_block <= 0:
        print("error: --meters-per-block must be > 0", file=sys.stderr)
        return 2
    if config.voxel_pitch_m <= 0:
        print("error: --voxel-pitch-m must be > 0", file=sys.stderr)
        return 2

    ifc_path = Path(config.ifc_path).expanduser().resolve()
    world_path = Path(config.world_path).expanduser().resolve()
    if not ifc_path.is_file():
        print(f"error: IFC file not found: {ifc_path}", file=sys.stderr)
        return 2

    if not dry_run and not world_path.exists():
        print(
            f"error: target world path does not exist: {world_path}",
            file=sys.stderr,
        )
        return 2

    try:
        ifc_file = ifcopenshell.open(str(ifc_path))
        _validate_ifc_types(ifc_file, config.include_types, label="include")
        _validate_ifc_types(ifc_file, config.exclude_types, label="exclude")
    except Exception as exc:
        print(f"error: failed to open/validate IFC model: {exc}", file=sys.stderr)
        return 1

    try:
        selected_elements = _collect_candidate_elements(
            ifc_file, config.include_types, config.exclude_types
        )
        element_type_counts = Counter(entity.is_a() for entity in selected_elements)
        geometry = _scan_geometry(ifc_file, selected_elements)
        ifc_unit_scale_m = float(ifcopenshell.util.unit.calculate_unit_scale(ifc_file))
    except Exception as exc:
        print(f"error: failed during IFC geometry scan: {exc}", file=sys.stderr)
        return 1

    print("IFC Import Report")
    print(f"ifc_path: {ifc_path}")
    print(f"world_path: {world_path}")
    print(f"schema: {ifc_file.schema}")
    print(f"origin_mode: {config.origin_mode}")
    print(f"meters_per_block: {config.meters_per_block}")
    print(f"voxel_pitch_m: {config.voxel_pitch_m}")
    print(f"y_offset: {config.y_offset}")
    if config.origin_mode == "fixed":
        print(f"fixed_origin_xz: ({config.fixed_origin_x}, {config.fixed_origin_z})")
    print(f"dimension: {config.dimension}")
    print(f"game: ({config.game_platform}, {config.game_version})")
    print(f"include_types: {list(config.include_types)}")
    print(f"exclude_types: {list(config.exclude_types)}")
    print(f"block_map_size: {len(config.block_map)}")
    print(f"selected_elements: {len(selected_elements)}")
    print(f"geometry_shapes: {geometry.shape_count}")
    print(f"empty_geometry_shapes: {geometry.empty_shape_count}")
    print(f"ifc_project_unit_scale_to_meters: {ifc_unit_scale_m}")
    print("geometry_output_units: meters")

    if geometry.bbox_min_proj is None or geometry.bbox_max_proj is None:
        print("geometry_bbox: <none>")
        if dry_run:
            print("dry_run: True")
            return 0
        print(
            "write_mode: not implemented yet (use --dry-run for analysis-only mode)",
            file=sys.stderr,
        )
        return 3

    # Geometry output was configured in SI meters.
    bbox_min_m = geometry.bbox_min_proj
    bbox_max_m = geometry.bbox_max_proj
    bbox_size_m = (
        bbox_max_m[0] - bbox_min_m[0],
        bbox_max_m[1] - bbox_min_m[1],
        bbox_max_m[2] - bbox_min_m[2],
    )
    bbox_min_project_units = tuple(value / ifc_unit_scale_m for value in bbox_min_m)
    bbox_max_project_units = tuple(value / ifc_unit_scale_m for value in bbox_max_m)

    placement = _plan_block_placement(bbox_min_m, bbox_max_m, config)
    chunk_count_x = placement.chunk_max_x - placement.chunk_min_x + 1
    chunk_count_z = placement.chunk_max_z - placement.chunk_min_z + 1
    chunk_count = chunk_count_x * chunk_count_z

    print(f"bbox_ifc_project_units_min: {_fmt_vec3(bbox_min_project_units)}")
    print(f"bbox_ifc_project_units_max: {_fmt_vec3(bbox_max_project_units)}")
    print(f"bbox_geometry_meters_min: {_fmt_vec3(bbox_min_m)}")
    print(f"bbox_geometry_meters_max: {_fmt_vec3(bbox_max_m)}")
    print(f"bbox_size_meters: {_fmt_vec3(bbox_size_m)}")
    print(f"planned_block_bbox_min: {_fmt_vec3(placement.bbox_min_blocks)}")
    print(f"planned_block_bbox_max: {_fmt_vec3(placement.bbox_max_blocks)}")
    print(f"planned_block_bbox_min_int: {_fmt_int3(placement.bbox_min_blocks_int)}")
    print(f"planned_block_bbox_max_int: {_fmt_int3(placement.bbox_max_blocks_int)}")
    print(
        "planned_chunk_range_xz: "
        f"x[{placement.chunk_min_x},{placement.chunk_max_x}] "
        f"z[{placement.chunk_min_z},{placement.chunk_max_z}]"
    )
    print(f"planned_chunk_count: {chunk_count}")

    top_types = element_type_counts.most_common(10)
    print("top_element_types:")
    for type_name, count in top_types:
        print(f"  {type_name}: {count}")

    if dry_run:
        print("dry_run: True")
        return 0

    print(
        "write_mode: not implemented yet (Phase 3 will write blocks to world)",
        file=sys.stderr,
    )
    return 3
