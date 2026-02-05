from __future__ import annotations

import math
import multiprocessing
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.unit
import numpy as np
import trimesh
import trimesh.voxel.creation

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


@dataclass(slots=True)
class PlacementTransform:
    shift_x_m: float
    shift_y_m: float
    shift_z_m: float
    world_x_offset_blocks: float
    world_z_offset_blocks: float


@dataclass(slots=True)
class VoxelizationSummary:
    shapes_with_faces: int
    shapes_voxelized: int
    shapes_failed: int
    raw_voxel_points: int
    unique_block_count: int
    block_bbox_min_int: tuple[int, int, int] | None
    block_bbox_max_int: tuple[int, int, int] | None
    chunk_min_x: int | None
    chunk_max_x: int | None
    chunk_min_z: int | None
    chunk_max_z: int | None
    type_counts: Counter[str]


@dataclass(slots=True)
class VoxelizationResult:
    summary: VoxelizationSummary
    block_types_by_coord: dict[tuple[int, int, int], str]
    material_buckets_by_coord: dict[tuple[int, int, int], str] = field(
        default_factory=dict
    )
    material_names_by_coord: dict[tuple[int, int, int], str] = field(
        default_factory=dict
    )


def _fmt_vec3(values: tuple[float, float, float], ndigits: int = 3) -> str:
    return f"({values[0]:.{ndigits}f}, {values[1]:.{ndigits}f}, {values[2]:.{ndigits}f})"


def _fmt_int3(values: tuple[int, int, int]) -> str:
    return f"({values[0]}, {values[1]}, {values[2]})"


def _fmt_ms(value_ms: float) -> str:
    return f"{value_ms:.1f}"


def _print_timing_summary(
    *,
    open_validate_ms: float,
    scan_ms: float,
    voxelize_ms: float | None,
    write_ms: float | None,
    total_ms: float,
) -> None:
    print("timing_summary_ms:")
    print(f"  open_validate: {_fmt_ms(open_validate_ms)}")
    print(f"  scan_geometry: {_fmt_ms(scan_ms)}")
    if voxelize_ms is not None:
        print(f"  voxelize: {_fmt_ms(voxelize_ms)}")
    if write_ms is not None:
        print(f"  write_world: {_fmt_ms(write_ms)}")
    print(f"  total: {_fmt_ms(total_ms)}")


_MATERIAL_BUCKET_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "wood",
        (
            "wood",
            "timber",
            "lumber",
            "hout",
            "hardhout",
            "multiplex",
            "plywood",
            "oak",
            "pine",
            "spruce",
        ),
    ),
    (
        "metal",
        (
            "steel",
            "staal",
            "metal",
            "aluminium",
            "aluminum",
            "copper",
            "zinc",
            "iron",
            "bronze",
        ),
    ),
    ("concrete", ("concrete", "beton", "cement")),
    (
        "masonry",
        ("masonry", "brick", "baksteen", "stone", "granite", "natuursteen", "kalkzandsteen"),
    ),
    ("glass", ("glass", "glas", "glazing")),
    (
        "soil",
        (
            "soil",
            "earth",
            "dirt",
            "gravel",
            "sand",
            "asphalt",
            "bulk-material",
            "fill",
        ),
    ),
)
_MATERIAL_BUCKET_ORDER = {
    bucket: index for index, (bucket, _) in enumerate(_MATERIAL_BUCKET_KEYWORDS)
}


def _extract_material_names(element: Any) -> tuple[str, ...]:
    try:
        materials = ifcopenshell.util.element.get_materials(element)
    except Exception:
        return ()

    unique_names: list[str] = []
    seen: set[str] = set()
    for material in materials:
        name = str(getattr(material, "Name", "") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        unique_names.append(name)
    return tuple(unique_names)


def _normalize_material_name(material_name: str) -> str:
    return material_name.strip().lower()


def _infer_material_bucket(material_names: tuple[str, ...]) -> str | None:
    if not material_names:
        return None

    bucket_scores: Counter[str] = Counter()
    for material_name in material_names:
        name_lc = material_name.lower()
        for bucket, keywords in _MATERIAL_BUCKET_KEYWORDS:
            if any(keyword in name_lc for keyword in keywords):
                bucket_scores[bucket] += 1

    if not bucket_scores:
        return None

    return max(
        bucket_scores.items(),
        key=lambda item: (item[1], -_MATERIAL_BUCKET_ORDER[item[0]]),
    )[0]


def _ifc_points_to_mc(points_ifc_m: np.ndarray, yaw_degrees: float) -> np.ndarray:
    """
    Convert IFC world coordinates (Z-up) to Minecraft-oriented coordinates.

    Mapping:
    - MC X <- IFC X
    - MC Y <- IFC Z  (up axis)
    - MC Z <- -IFC Y
    """

    points_mc = np.empty_like(points_ifc_m)
    points_mc[:, 0] = points_ifc_m[:, 0]
    points_mc[:, 1] = points_ifc_m[:, 2]
    points_mc[:, 2] = -points_ifc_m[:, 1]

    if yaw_degrees != 0.0:
        yaw_rad = math.radians(yaw_degrees)
        cos_yaw = math.cos(yaw_rad)
        sin_yaw = math.sin(yaw_rad)
        x = points_mc[:, 0].copy()
        z = points_mc[:, 2].copy()
        points_mc[:, 0] = x * cos_yaw - z * sin_yaw
        points_mc[:, 2] = x * sin_yaw + z * cos_yaw

    return points_mc


def _transform_bbox_ifc_to_mc(
    bbox_min_ifc_m: tuple[float, float, float],
    bbox_max_ifc_m: tuple[float, float, float],
    yaw_degrees: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    min_x, min_y, min_z = bbox_min_ifc_m
    max_x, max_y, max_z = bbox_max_ifc_m
    corners = np.asarray(
        [
            [min_x, min_y, min_z],
            [min_x, min_y, max_z],
            [min_x, max_y, min_z],
            [min_x, max_y, max_z],
            [max_x, min_y, min_z],
            [max_x, min_y, max_z],
            [max_x, max_y, min_z],
            [max_x, max_y, max_z],
        ],
        dtype=np.float64,
    )
    transformed = _ifc_points_to_mc(corners, yaw_degrees)
    min_v = transformed.min(axis=0)
    max_v = transformed.max(axis=0)
    return (
        (float(min_v[0]), float(min_v[1]), float(min_v[2])),
        (float(max_v[0]), float(max_v[1]), float(max_v[2])),
    )


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
    transform = _compute_placement_transform(bbox_min_m, bbox_max_m, config)

    meters_per_block = config.meters_per_block
    min_block_x = (
        (min_x + transform.shift_x_m) / meters_per_block + transform.world_x_offset_blocks
    )
    min_block_y = (min_y + transform.shift_y_m) / meters_per_block + float(config.y_offset)
    min_block_z = (
        (min_z + transform.shift_z_m) / meters_per_block + transform.world_z_offset_blocks
    )

    max_block_x = (
        (max_x + transform.shift_x_m) / meters_per_block + transform.world_x_offset_blocks
    )
    max_block_y = (max_y + transform.shift_y_m) / meters_per_block + float(config.y_offset)
    max_block_z = (
        (max_z + transform.shift_z_m) / meters_per_block + transform.world_z_offset_blocks
    )

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


def _compute_placement_transform(
    bbox_min_m: tuple[float, float, float],
    bbox_max_m: tuple[float, float, float],
    config: ImportConfig,
) -> PlacementTransform:
    min_x, min_y, min_z = bbox_min_m
    max_x, _, max_z = bbox_max_m

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

    return PlacementTransform(
        shift_x_m=shift_x,
        shift_y_m=shift_y,
        shift_z_m=shift_z,
        world_x_offset_blocks=world_x_offset_blocks,
        world_z_offset_blocks=world_z_offset_blocks,
    )


def _voxelize_geometry(
    ifc_file: ifcopenshell.file,
    entities: list[Any],
    *,
    config: ImportConfig,
    transform: PlacementTransform,
) -> VoxelizationResult:
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    settings.set("convert-back-units", False)

    iterator = ifcopenshell.geom.iterator(
        settings,
        ifc_file,
        max(1, multiprocessing.cpu_count()),
        include=entities,
    )
    if not iterator.initialize():
        return VoxelizationResult(
            summary=VoxelizationSummary(
                shapes_with_faces=0,
                shapes_voxelized=0,
                shapes_failed=0,
                raw_voxel_points=0,
                unique_block_count=0,
                block_bbox_min_int=None,
                block_bbox_max_int=None,
                chunk_min_x=None,
                chunk_max_x=None,
                chunk_min_z=None,
                chunk_max_z=None,
                type_counts=Counter(),
            ),
            block_types_by_coord={},
        )

    occupied_blocks: dict[tuple[int, int, int], str] = {}
    occupied_material_buckets: dict[tuple[int, int, int], str] = {}
    occupied_material_names: dict[tuple[int, int, int], str] = {}

    shapes_with_faces = 0
    shapes_voxelized = 0
    shapes_failed = 0
    raw_voxel_points = 0

    while True:
        shape = iterator.get()
        verts = shape.geometry.verts
        faces = shape.geometry.faces
        if not verts or not faces:
            if not iterator.next():
                break
            continue

        shapes_with_faces += 1
        try:
            vertices = np.asarray(verts, dtype=np.float64).reshape((-1, 3))
            face_indices = np.asarray(faces, dtype=np.int64).reshape((-1, 3))
            mesh = trimesh.Trimesh(vertices=vertices, faces=face_indices, process=False)
            if mesh.is_empty:
                if not iterator.next():
                    break
                continue

            voxel_grid = trimesh.voxel.creation.voxelize(
                mesh,
                pitch=float(config.voxel_pitch_m),
                method=config.voxel_method,
            )
            if voxel_grid is None:
                if not iterator.next():
                    break
                continue

            points_ifc_m = np.asarray(voxel_grid.points, dtype=np.float64)
            if points_ifc_m.size == 0:
                if not iterator.next():
                    break
                continue

            points_mc_m = _ifc_points_to_mc(points_ifc_m, config.yaw_degrees)

            raw_voxel_points += int(points_mc_m.shape[0])
            shapes_voxelized += 1
            try:
                element = ifc_file.by_id(int(shape.id))
                element_type = str(element.is_a())
                element_material_names = _extract_material_names(element)
                element_material_bucket = _infer_material_bucket(element_material_names)
                element_material_name = (
                    _normalize_material_name(element_material_names[0])
                    if element_material_names
                    else None
                )
            except Exception:
                element_type = "<unknown>"
                element_material_bucket = None
                element_material_name = None

            bx = np.floor(
                (points_mc_m[:, 0] + transform.shift_x_m) / config.meters_per_block
                + transform.world_x_offset_blocks
            ).astype(np.int64)
            by = np.floor(
                (points_mc_m[:, 1] + transform.shift_y_m) / config.meters_per_block
                + float(config.y_offset)
            ).astype(np.int64)
            bz = np.floor(
                (points_mc_m[:, 2] + transform.shift_z_m) / config.meters_per_block
                + transform.world_z_offset_blocks
            ).astype(np.int64)

            unique_for_shape = np.unique(np.column_stack((bx, by, bz)), axis=0)
            for block_xyz in unique_for_shape:
                coord = (int(block_xyz[0]), int(block_xyz[1]), int(block_xyz[2]))
                existing_type = occupied_blocks.get(coord)
                if existing_type is None:
                    occupied_blocks[coord] = element_type
                    if element_material_bucket is not None:
                        occupied_material_buckets[coord] = element_material_bucket
                    else:
                        occupied_material_buckets.pop(coord, None)
                    if element_material_name is not None:
                        occupied_material_names[coord] = element_material_name
                    else:
                        occupied_material_names.pop(coord, None)
                else:
                    winning_type = _resolve_overlap_ifc_type(
                        existing_type, element_type, config
                    )
                    if winning_type != existing_type:
                        occupied_blocks[coord] = winning_type
                        if element_material_bucket is not None:
                            occupied_material_buckets[coord] = element_material_bucket
                        else:
                            occupied_material_buckets.pop(coord, None)
                        if element_material_name is not None:
                            occupied_material_names[coord] = element_material_name
                        else:
                            occupied_material_names.pop(coord, None)

        except Exception:
            shapes_failed += 1

        if not iterator.next():
            break

    if not occupied_blocks:
        return VoxelizationResult(
            summary=VoxelizationSummary(
                shapes_with_faces=shapes_with_faces,
                shapes_voxelized=shapes_voxelized,
                shapes_failed=shapes_failed,
                raw_voxel_points=raw_voxel_points,
                unique_block_count=0,
                block_bbox_min_int=None,
                block_bbox_max_int=None,
                chunk_min_x=None,
                chunk_max_x=None,
                chunk_min_z=None,
                chunk_max_z=None,
                type_counts=Counter(),
            ),
            block_types_by_coord={},
        )

    min_x = min(x for x, _, _ in occupied_blocks.keys())
    min_y = min(y for _, y, _ in occupied_blocks.keys())
    min_z = min(z for _, _, z in occupied_blocks.keys())
    max_x = max(x for x, _, _ in occupied_blocks.keys())
    max_y = max(y for _, y, _ in occupied_blocks.keys())
    max_z = max(z for _, _, z in occupied_blocks.keys())

    chunk_min_x = math.floor(min_x / 16)
    chunk_max_x = math.floor(max_x / 16)
    chunk_min_z = math.floor(min_z / 16)
    chunk_max_z = math.floor(max_z / 16)
    type_counts = Counter(occupied_blocks.values())

    return VoxelizationResult(
        summary=VoxelizationSummary(
            shapes_with_faces=shapes_with_faces,
            shapes_voxelized=shapes_voxelized,
            shapes_failed=shapes_failed,
            raw_voxel_points=raw_voxel_points,
            unique_block_count=len(occupied_blocks),
            block_bbox_min_int=(min_x, min_y, min_z),
            block_bbox_max_int=(max_x, max_y, max_z),
            chunk_min_x=chunk_min_x,
            chunk_max_x=chunk_max_x,
            chunk_min_z=chunk_min_z,
            chunk_max_z=chunk_max_z,
            type_counts=type_counts,
        ),
        block_types_by_coord=occupied_blocks,
        material_buckets_by_coord=occupied_material_buckets,
        material_names_by_coord=occupied_material_names,
    )


def _parse_block_name(block_name: str) -> tuple[str, str]:
    raw = block_name.strip()
    if not raw:
        return ("minecraft", "stone")
    if ":" in raw:
        namespace, base_name = raw.split(":", 1)
        namespace = namespace.strip() or "minecraft"
        base_name = base_name.strip() or "stone"
        return (namespace, base_name)
    return ("minecraft", raw)


_HORIZONTAL_DIRECTIONS: tuple[tuple[str, tuple[int, int]], ...] = (
    ("north", (0, -1)),
    ("east", (1, 0)),
    ("south", (0, 1)),
    ("west", (-1, 0)),
)


def _connection_properties_for_block(
    block_name: str,
    coord: tuple[int, int, int],
    resolved_block_names: dict[tuple[int, int, int], str],
) -> dict[str, str] | None:
    namespace, base_name = _parse_block_name(block_name)
    if namespace != "minecraft":
        return None

    supports_fence_like_connections = (
        base_name.endswith("_fence")
        or base_name == "iron_bars"
        or base_name.endswith("_glass_pane")
    )
    supports_wall_connections = base_name.endswith("_wall")
    if not supports_fence_like_connections and not supports_wall_connections:
        return None

    x, y, z = coord
    neighbor_connected: dict[str, bool] = {}
    for direction_name, (delta_x, delta_z) in _HORIZONTAL_DIRECTIONS:
        neighbor_connected[direction_name] = (
            (x + delta_x, y, z + delta_z) in resolved_block_names
        )

    properties: dict[str, str] = {}
    if supports_wall_connections:
        for direction_name, is_connected in neighbor_connected.items():
            properties[direction_name] = "low" if is_connected else "none"

        connected_directions = {
            direction_name
            for direction_name, is_connected in neighbor_connected.items()
            if is_connected
        }
        is_straight_line = connected_directions in (
            {"north", "south"},
            {"east", "west"},
        )
        properties["up"] = "false" if is_straight_line else "true"
    else:
        for direction_name, is_connected in neighbor_connected.items():
            properties[direction_name] = "true" if is_connected else "false"

    properties["waterlogged"] = "false"
    return properties


def _resolve_block_name(
    ifc_type: str,
    material_name: str | None,
    material_bucket: str | None,
    config: ImportConfig,
) -> str:
    if material_name is not None:
        typed_material_name_key = f"{ifc_type}|material_name:{material_name}"
        if typed_material_name_key in config.block_map:
            return config.block_map[typed_material_name_key]
    if material_bucket is not None:
        typed_material_key = f"{ifc_type}|{material_bucket}"
        if typed_material_key in config.block_map:
            return config.block_map[typed_material_key]
    if material_name is not None:
        material_name_key = f"material_name:{material_name}"
        if material_name_key in config.block_map:
            return config.block_map[material_name_key]
    if material_bucket is not None:
        material_key = f"material:{material_bucket}"
        if material_key in config.block_map:
            return config.block_map[material_key]
    if ifc_type in config.block_map:
        return config.block_map[ifc_type]
    return "minecraft:stone"


def _resolve_overlap_ifc_type(
    existing_ifc_type: str,
    candidate_ifc_type: str,
    config: ImportConfig,
) -> str:
    existing_priority = int(config.type_priority.get(existing_ifc_type, 0))
    candidate_priority = int(config.type_priority.get(candidate_ifc_type, 0))
    if candidate_priority > existing_priority:
        return candidate_ifc_type
    return existing_ifc_type


def _chunk_coords_for_block(x: int, z: int) -> tuple[int, int]:
    return (math.floor(x / 16), math.floor(z / 16))


def _count_touched_chunks(block_types_by_coord: dict[tuple[int, int, int], str]) -> int:
    if not block_types_by_coord:
        return 0
    chunk_coords = {
        _chunk_coords_for_block(int(x), int(z))
        for x, _, z in block_types_by_coord.keys()
    }
    return len(chunk_coords)


def _write_blocks_to_world(
    config: ImportConfig,
    block_types_by_coord: dict[tuple[int, int, int], str],
    material_buckets_by_coord: dict[tuple[int, int, int], str],
    material_names_by_coord: dict[tuple[int, int, int], str],
) -> tuple[int, Counter[str], int]:
    import amulet
    from amulet.api.block import Block
    from amulet_nbt import StringTag

    level = amulet.load_level(str(config.world_path))
    game_version = (config.game_platform, config.game_version)
    placed_by_block_name: Counter[str] = Counter()
    block_cache: dict[str, Block] = {}
    connected_block_cache: dict[
        tuple[str, tuple[tuple[str, str], ...]],
        Block,
    ] = {}
    touched_chunks: set[tuple[int, int]] = set()
    resolved_block_names = {
        coord: _resolve_block_name(
            ifc_type,
            material_names_by_coord.get(coord),
            material_buckets_by_coord.get(coord),
            config,
        )
        for coord, ifc_type in block_types_by_coord.items()
    }

    def _write_sort_key(
        item: tuple[tuple[int, int, int], str],
    ) -> tuple[int, int, int, int, int]:
        (x, y, z), _ = item
        chunk_x, chunk_z = _chunk_coords_for_block(int(x), int(z))
        return (chunk_x, chunk_z, int(y), int(x), int(z))

    sorted_items = sorted(
        block_types_by_coord.items(),
        key=_write_sort_key,
    )

    try:
        for (x, y, z), ifc_type in sorted_items:
            coord = (x, y, z)
            block_name = resolved_block_names[coord]
            connection_properties = _connection_properties_for_block(
                block_name,
                coord,
                resolved_block_names,
            )
            if connection_properties is None:
                block = block_cache.get(block_name)
                if block is None:
                    namespace, base_name = _parse_block_name(block_name)
                    block = Block(namespace, base_name)
                    block_cache[block_name] = block
            else:
                connection_key = tuple(sorted(connection_properties.items()))
                cache_key = (block_name, connection_key)
                block = connected_block_cache.get(cache_key)
                if block is None:
                    namespace, base_name = _parse_block_name(block_name)
                    properties_nbt = {
                        key: StringTag(value)
                        for key, value in connection_key
                    }
                    block = Block(namespace, base_name, properties_nbt)
                    connected_block_cache[cache_key] = block

            touched_chunks.add(_chunk_coords_for_block(int(x), int(z)))
            level.set_version_block(
                int(x),
                int(y),
                int(z),
                config.dimension,
                game_version,
                block,
            )
            placed_by_block_name[block_name] += 1

        level.save()
    finally:
        level.close()

    return (sum(placed_by_block_name.values()), placed_by_block_name, len(touched_chunks))


def run_import(config: ImportConfig, *, dry_run: bool = False) -> int:
    if config.meters_per_block <= 0:
        print("error: --meters-per-block must be > 0", file=sys.stderr)
        return 2
    if config.voxel_pitch_m <= 0:
        print("error: --voxel-pitch-m must be > 0", file=sys.stderr)
        return 2
    if config.ground_clearance < 0:
        print("error: --ground-clearance must be >= 0", file=sys.stderr)
        return 2

    ifc_path = Path(config.ifc_path).expanduser().resolve()
    world_path = Path(config.world_path).expanduser().resolve()
    config.ifc_path = ifc_path
    config.world_path = world_path
    y_offset_input = config.y_offset
    if config.snap_to_superflat:
        config.y_offset = config.superflat_ground_y + config.ground_clearance
    if not ifc_path.is_file():
        print(f"error: IFC file not found: {ifc_path}", file=sys.stderr)
        return 2

    if not dry_run and not world_path.exists():
        print(
            f"error: target world path does not exist: {world_path}",
            file=sys.stderr,
        )
        return 2

    run_started_at = time.perf_counter()
    open_validate_started_at = time.perf_counter()
    try:
        ifc_file = ifcopenshell.open(str(ifc_path))
        _validate_ifc_types(ifc_file, config.include_types, label="include")
        _validate_ifc_types(ifc_file, config.exclude_types, label="exclude")
    except Exception as exc:
        print(f"error: failed to open/validate IFC model: {exc}", file=sys.stderr)
        return 1
    open_validate_ms = (time.perf_counter() - open_validate_started_at) * 1000.0

    scan_started_at = time.perf_counter()
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
    scan_ms = (time.perf_counter() - scan_started_at) * 1000.0

    print("IFC Import Report")
    print(f"ifc_path: {ifc_path}")
    print(f"world_path: {world_path}")
    print(f"schema: {ifc_file.schema}")
    print(f"origin_mode: {config.origin_mode}")
    print(f"meters_per_block: {config.meters_per_block}")
    print(f"voxel_pitch_m: {config.voxel_pitch_m}")
    print(f"voxelize: {config.voxelize}")
    if config.voxelize:
        print(f"voxel_method: {config.voxel_method}")
    print(f"yaw_degrees: {config.yaw_degrees}")
    print(f"snap_to_superflat: {config.snap_to_superflat}")
    print(f"superflat_ground_y: {config.superflat_ground_y}")
    print(f"ground_clearance: {config.ground_clearance}")
    print(f"y_offset_input: {y_offset_input}")
    print(f"y_offset_effective: {config.y_offset}")
    if config.origin_mode == "fixed":
        print(f"fixed_origin_xz: ({config.fixed_origin_x}, {config.fixed_origin_z})")
    print(f"dimension: {config.dimension}")
    print(f"game: ({config.game_platform}, {config.game_version})")
    print(f"include_types: {list(config.include_types)}")
    print(f"exclude_types: {list(config.exclude_types)}")
    print(f"block_map_size: {len(config.block_map)}")
    print(f"type_priority_size: {len(config.type_priority)}")
    print(f"selected_elements: {len(selected_elements)}")
    print(f"geometry_shapes: {geometry.shape_count}")
    print(f"empty_geometry_shapes: {geometry.empty_shape_count}")
    print(f"ifc_project_unit_scale_to_meters: {ifc_unit_scale_m}")
    print("geometry_output_units: meters")

    if geometry.bbox_min_proj is None or geometry.bbox_max_proj is None:
        print("geometry_bbox: <none>")
        if dry_run:
            total_ms = (time.perf_counter() - run_started_at) * 1000.0
            _print_timing_summary(
                open_validate_ms=open_validate_ms,
                scan_ms=scan_ms,
                voxelize_ms=None,
                write_ms=None,
                total_ms=total_ms,
            )
            print("dry_run: True")
            return 0
        print("error: model has no geometric output to write", file=sys.stderr)
        return 1

    # Geometry output was configured in SI meters (IFC world axes, Z-up).
    bbox_min_ifc_m = geometry.bbox_min_proj
    bbox_max_ifc_m = geometry.bbox_max_proj
    bbox_size_ifc_m = (
        bbox_max_ifc_m[0] - bbox_min_ifc_m[0],
        bbox_max_ifc_m[1] - bbox_min_ifc_m[1],
        bbox_max_ifc_m[2] - bbox_min_ifc_m[2],
    )
    bbox_min_project_units = tuple(value / ifc_unit_scale_m for value in bbox_min_ifc_m)
    bbox_max_project_units = tuple(value / ifc_unit_scale_m for value in bbox_max_ifc_m)
    bbox_min_mc_m, bbox_max_mc_m = _transform_bbox_ifc_to_mc(
        bbox_min_ifc_m, bbox_max_ifc_m, config.yaw_degrees
    )
    bbox_size_mc_m = (
        bbox_max_mc_m[0] - bbox_min_mc_m[0],
        bbox_max_mc_m[1] - bbox_min_mc_m[1],
        bbox_max_mc_m[2] - bbox_min_mc_m[2],
    )

    placement = _plan_block_placement(bbox_min_mc_m, bbox_max_mc_m, config)
    transform = _compute_placement_transform(bbox_min_mc_m, bbox_max_mc_m, config)
    chunk_count_x = placement.chunk_max_x - placement.chunk_min_x + 1
    chunk_count_z = placement.chunk_max_z - placement.chunk_min_z + 1
    chunk_count = chunk_count_x * chunk_count_z

    print(f"bbox_ifc_project_units_min: {_fmt_vec3(bbox_min_project_units)}")
    print(f"bbox_ifc_project_units_max: {_fmt_vec3(bbox_max_project_units)}")
    print(f"bbox_ifc_meters_min: {_fmt_vec3(bbox_min_ifc_m)}")
    print(f"bbox_ifc_meters_max: {_fmt_vec3(bbox_max_ifc_m)}")
    print(f"bbox_ifc_size_meters: {_fmt_vec3(bbox_size_ifc_m)}")
    print(f"bbox_mc_meters_min: {_fmt_vec3(bbox_min_mc_m)}")
    print(f"bbox_mc_meters_max: {_fmt_vec3(bbox_max_mc_m)}")
    print(f"bbox_mc_size_meters: {_fmt_vec3(bbox_size_mc_m)}")
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

    should_voxelize = config.voxelize or not dry_run
    voxel_result: VoxelizationResult | None = None
    voxelize_ms: float | None = None
    if not dry_run and not config.voxelize:
        print("voxelize_auto_enabled_for_write: True")
    if should_voxelize:
        voxelize_started_at = time.perf_counter()
        try:
            voxel_result = _voxelize_geometry(
                ifc_file,
                selected_elements,
                config=config,
                transform=transform,
            )
            voxelize_ms = (time.perf_counter() - voxelize_started_at) * 1000.0
            voxel_summary = voxel_result.summary
            print("voxelization_summary:")
            print(f"  shapes_with_faces: {voxel_summary.shapes_with_faces}")
            print(f"  shapes_voxelized: {voxel_summary.shapes_voxelized}")
            print(f"  shapes_failed: {voxel_summary.shapes_failed}")
            print(f"  raw_voxel_points: {voxel_summary.raw_voxel_points}")
            print(f"  unique_block_count: {voxel_summary.unique_block_count}")
            if voxel_summary.block_bbox_min_int is not None:
                print(
                    "  voxel_block_bbox_min_int: "
                    f"{_fmt_int3(voxel_summary.block_bbox_min_int)}"
                )
                print(
                    "  voxel_block_bbox_max_int: "
                    f"{_fmt_int3(voxel_summary.block_bbox_max_int)}"
                )
                print(
                    "  voxel_chunk_range_xz: "
                    f"x[{voxel_summary.chunk_min_x},{voxel_summary.chunk_max_x}] "
                    f"z[{voxel_summary.chunk_min_z},{voxel_summary.chunk_max_z}]"
                )
                voxel_chunk_count_x = voxel_summary.chunk_max_x - voxel_summary.chunk_min_x + 1
                voxel_chunk_count_z = voxel_summary.chunk_max_z - voxel_summary.chunk_min_z + 1
                print(f"  voxel_chunk_count: {voxel_chunk_count_x * voxel_chunk_count_z}")
            else:
                print("  voxel_block_bbox: <none>")

            print("  top_voxelized_types:")
            for type_name, count in voxel_summary.type_counts.most_common(10):
                print(f"    {type_name}: {count}")
            block_preview_counts: Counter[str] = Counter()
            material_bucket_counts = Counter(
                voxel_result.material_buckets_by_coord.values()
            )
            for coord, ifc_type in voxel_result.block_types_by_coord.items():
                block_preview_counts[
                    _resolve_block_name(
                        ifc_type,
                        voxel_result.material_names_by_coord.get(coord),
                        voxel_result.material_buckets_by_coord.get(coord),
                        config,
                    )
                ] += 1
            if material_bucket_counts:
                print("  top_material_buckets:")
                for bucket_name, count in material_bucket_counts.most_common(10):
                    print(f"    {bucket_name}: {count}")
            print("  top_resolved_blocks:")
            for block_name, count in block_preview_counts.most_common(10):
                print(f"    {block_name}: {count}")
        except Exception as exc:
            print(f"error: voxelization failed: {exc}", file=sys.stderr)
            return 1

    if dry_run:
        total_ms = (time.perf_counter() - run_started_at) * 1000.0
        _print_timing_summary(
            open_validate_ms=open_validate_ms,
            scan_ms=scan_ms,
            voxelize_ms=voxelize_ms,
            write_ms=None,
            total_ms=total_ms,
        )
        print("dry_run: True")
        return 0

    if voxel_result is None:
        print("error: write mode requires voxelization result", file=sys.stderr)
        return 1

    if not voxel_result.block_types_by_coord:
        print("write_summary:")
        print("  placed_blocks: 0")
        print("  touched_chunks: 0")
        print("  placed_block_types: <none>")
        total_ms = (time.perf_counter() - run_started_at) * 1000.0
        _print_timing_summary(
            open_validate_ms=open_validate_ms,
            scan_ms=scan_ms,
            voxelize_ms=voxelize_ms,
            write_ms=0.0,
            total_ms=total_ms,
        )
        return 0

    write_started_at = time.perf_counter()
    try:
        placed_count, placed_by_block_name, touched_chunks = _write_blocks_to_world(
            config,
            voxel_result.block_types_by_coord,
            voxel_result.material_buckets_by_coord,
            voxel_result.material_names_by_coord,
        )
    except Exception as exc:
        print(f"error: failed to write world blocks: {exc}", file=sys.stderr)
        return 1
    write_ms = (time.perf_counter() - write_started_at) * 1000.0

    print("write_summary:")
    print(f"  placed_blocks: {placed_count}")
    print(f"  touched_chunks: {touched_chunks}")
    print("  placed_block_types:")
    for block_name, count in placed_by_block_name.most_common():
        print(f"    {block_name}: {count}")
    total_ms = (time.perf_counter() - run_started_at) * 1000.0
    _print_timing_summary(
        open_validate_ms=open_validate_ms,
        scan_ms=scan_ms,
        voxelize_ms=voxelize_ms,
        write_ms=write_ms,
        total_ms=total_ms,
    )
    return 0
