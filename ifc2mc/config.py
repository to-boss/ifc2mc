from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

OriginMode = Literal["centered", "min_corner", "fixed"]
VoxelMethod = Literal["subdivide", "ray", "binvox"]


@dataclass(slots=True)
class ImportConfig:
    """Typed Python config for IFC -> Minecraft imports."""

    ifc_path: Path
    world_path: Path
    origin_mode: OriginMode = "centered"
    meters_per_block: float = 0.5
    voxel_pitch_m: float = 0.5
    voxelize: bool = False
    voxel_method: VoxelMethod = "subdivide"
    yaw_degrees: float = 0.0
    y_offset: int = 64
    snap_to_superflat: bool = True
    superflat_ground_y: int = -60
    ground_clearance: int = 1
    fixed_origin_x: int = 0
    fixed_origin_z: int = 0
    dimension: str = "minecraft:overworld"
    game_platform: str = "java"
    game_version: int = 3700
    include_types: tuple[str, ...] = ()
    exclude_types: tuple[str, ...] = ()
    block_map: dict[str, str] = field(default_factory=dict)
    type_priority: dict[str, int] = field(default_factory=dict)


def default_block_map() -> dict[str, str]:
    """Default IFC/material -> Minecraft block mapping."""

    return {
        # Material bucket defaults.
        "material:wood": "minecraft:oak_planks",
        "material:metal": "minecraft:iron_block",
        "material:concrete": "minecraft:smooth_stone",
        "material:masonry": "minecraft:stone_bricks",
        "material:glass": "minecraft:glass",
        "material:soil": "minecraft:dirt",
        # Type+material overrides for more recognizable silhouettes.
        "IfcRailing|wood": "minecraft:oak_fence",
        "IfcRailing|metal": "minecraft:iron_bars",
        "IfcBeam": "minecraft:stone",
        "IfcColumn": "minecraft:stone_bricks",
        "IfcSlab": "minecraft:smooth_stone",
        "IfcFooting": "minecraft:andesite",
        "IfcMember": "minecraft:polished_andesite",
        "IfcWall": "minecraft:stone_bricks",
        "IfcEarthworksFill": "minecraft:dirt",
        "IfcBuildingElementProxy": "minecraft:stone",
        "IfcBridgePart": "minecraft:stone_bricks",
        "IfcElementAssembly": "minecraft:stone_bricks",
        "IfcSign": "minecraft:stone",
    }


def default_type_priority() -> dict[str, int]:
    """Default deterministic priority for overlapping IFC voxels."""

    return {
        "IfcFooting": 100,
        "IfcColumn": 90,
        "IfcBeam": 80,
        "IfcSlab": 70,
        "IfcWall": 60,
        "IfcMember": 50,
    }
