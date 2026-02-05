from __future__ import annotations

from pathlib import Path

import numpy as np

from ifc2mc.config import ImportConfig
from ifc2mc.importer import (
    _count_touched_chunks,
    _compute_placement_transform,
    _ifc_points_to_mc,
    _parse_block_name,
    _plan_block_placement,
    _resolve_block_name,
    _resolve_overlap_ifc_type,
    run_import,
)


def _base_config(**kwargs: object) -> ImportConfig:
    params: dict[str, object] = {
        "ifc_path": Path("missing.ifc"),
        "world_path": Path("."),
    }
    params.update(kwargs)
    return ImportConfig(**params)


def test_ifc_points_to_mc_axis_mapping_without_rotation() -> None:
    points = np.asarray([[1.0, 2.0, 3.0], [-4.0, 0.0, 5.0]], dtype=np.float64)

    mapped = _ifc_points_to_mc(points, yaw_degrees=0.0)

    expected = np.asarray([[1.0, 3.0, -2.0], [-4.0, 5.0, -0.0]], dtype=np.float64)
    assert np.allclose(mapped, expected)


def test_ifc_points_to_mc_applies_yaw_rotation() -> None:
    points = np.asarray([[1.0, 2.0, 3.0]], dtype=np.float64)

    mapped = _ifc_points_to_mc(points, yaw_degrees=90.0)

    expected = np.asarray([[2.0, 3.0, 1.0]], dtype=np.float64)
    assert np.allclose(mapped, expected)


def test_compute_placement_transform_modes() -> None:
    bbox_min = (-10.0, 2.0, 4.0)
    bbox_max = (2.0, 7.0, 14.0)

    centered = _compute_placement_transform(
        bbox_min,
        bbox_max,
        _base_config(origin_mode="centered"),
    )
    assert centered.shift_x_m == 4.0
    assert centered.shift_y_m == -2.0
    assert centered.shift_z_m == -9.0
    assert centered.world_x_offset_blocks == 0.0
    assert centered.world_z_offset_blocks == 0.0

    min_corner = _compute_placement_transform(
        bbox_min,
        bbox_max,
        _base_config(origin_mode="min_corner"),
    )
    assert min_corner.shift_x_m == 10.0
    assert min_corner.shift_y_m == -2.0
    assert min_corner.shift_z_m == -4.0

    fixed = _compute_placement_transform(
        bbox_min,
        bbox_max,
        _base_config(origin_mode="fixed", fixed_origin_x=12, fixed_origin_z=-7),
    )
    assert fixed.shift_x_m == 0.0
    assert fixed.shift_y_m == -2.0
    assert fixed.shift_z_m == 0.0
    assert fixed.world_x_offset_blocks == 12.0
    assert fixed.world_z_offset_blocks == -7.0


def test_plan_block_placement_integer_and_chunk_bounds() -> None:
    plan = _plan_block_placement(
        (0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
        _base_config(origin_mode="min_corner", meters_per_block=0.5, y_offset=64),
    )

    assert plan.bbox_min_blocks_int == (0, 64, 0)
    assert plan.bbox_max_blocks_int == (1, 65, 1)
    assert plan.chunk_min_x == 0
    assert plan.chunk_max_x == 0
    assert plan.chunk_min_z == 0
    assert plan.chunk_max_z == 0


def test_plan_block_placement_handles_negative_chunk_flooring() -> None:
    plan = _plan_block_placement(
        (-0.1, 0.0, -16.2),
        (0.1, 1.0, -15.8),
        _base_config(origin_mode="fixed", meters_per_block=1.0, y_offset=0),
    )

    assert plan.bbox_min_blocks_int == (-1, 0, -17)
    assert plan.bbox_max_blocks_int == (0, 0, -16)
    assert plan.chunk_min_z == -2
    assert plan.chunk_max_z == -1


def test_parse_block_name_variants() -> None:
    assert _parse_block_name("") == ("minecraft", "stone")
    assert _parse_block_name("stone_bricks") == ("minecraft", "stone_bricks")
    assert _parse_block_name("custom:polished") == ("custom", "polished")
    assert _parse_block_name(":andesite") == ("minecraft", "andesite")
    assert _parse_block_name("minecraft:") == ("minecraft", "stone")


def test_resolve_block_name_prefers_config_map() -> None:
    cfg = _base_config(block_map={"IfcColumn": "minecraft:stone_bricks"})
    assert _resolve_block_name("IfcColumn", cfg) == "minecraft:stone_bricks"
    assert _resolve_block_name("IfcWall", cfg) == "minecraft:stone"


def test_resolve_overlap_ifc_type_uses_priority_and_stable_ties() -> None:
    cfg = _base_config(type_priority={"IfcSlab": 50, "IfcBeam": 10})
    assert _resolve_overlap_ifc_type("IfcBeam", "IfcSlab", cfg) == "IfcSlab"
    assert _resolve_overlap_ifc_type("IfcSlab", "IfcBeam", cfg) == "IfcSlab"

    tie_cfg = _base_config(type_priority={})
    assert _resolve_overlap_ifc_type("IfcWall", "IfcColumn", tie_cfg) == "IfcWall"


def test_count_touched_chunks_handles_negative_coordinates() -> None:
    blocks = {
        (0, 64, 0): "IfcWall",
        (15, 64, 15): "IfcWall",
        (16, 64, 0): "IfcWall",
        (-1, 64, -1): "IfcWall",
        (-17, 64, -1): "IfcWall",
    }
    assert _count_touched_chunks(blocks) == 4


def test_run_import_validates_numeric_inputs_early() -> None:
    assert run_import(_base_config(meters_per_block=0.0), dry_run=True) == 2
    assert run_import(_base_config(voxel_pitch_m=0.0), dry_run=True) == 2
    assert run_import(_base_config(ground_clearance=-1), dry_run=True) == 2


def test_run_import_fails_for_missing_ifc_file() -> None:
    cfg = _base_config(ifc_path=Path("does-not-exist.ifc"), world_path=Path("."))
    assert run_import(cfg, dry_run=True) == 2
