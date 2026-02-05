from __future__ import annotations

import argparse
from pathlib import Path

from .config import ImportConfig, default_block_map
from .importer import run_import


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ifc2mc", description="Import IFC models into Minecraft worlds."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser(
        "import", help="Import an IFC model into a Minecraft world."
    )
    import_parser.add_argument("--ifc", required=True, type=Path, help="Input IFC file.")
    import_parser.add_argument(
        "--world", required=True, type=Path, help="Target Minecraft world path."
    )
    import_parser.add_argument(
        "--origin-mode",
        choices=("centered", "min_corner", "fixed"),
        default="centered",
        help="How IFC coordinates are anchored in Minecraft space.",
    )
    import_parser.add_argument(
        "--meters-per-block",
        type=float,
        default=0.5,
        help="Scale conversion from meters to blocks.",
    )
    import_parser.add_argument(
        "--voxel-pitch-m",
        type=float,
        default=0.5,
        help="Voxel pitch in meters.",
    )
    import_parser.add_argument(
        "--voxelize",
        action="store_true",
        help="Run Phase 2 voxelization and block footprint reporting.",
    )
    import_parser.add_argument(
        "--voxel-method",
        choices=("subdivide", "ray", "binvox"),
        default="subdivide",
        help="trimesh voxelization backend.",
    )
    import_parser.add_argument(
        "--yaw-deg",
        type=float,
        default=0.0,
        help="Rotate model around vertical axis after IFC->Minecraft axis conversion.",
    )
    import_parser.add_argument(
        "--y-offset", type=int, default=64, help="World Y offset for placement."
    )
    import_parser.add_argument(
        "--snap-to-superflat",
        dest="snap_to_superflat",
        action="store_true",
        default=True,
        help="Auto-place using superflat ground level and clearance.",
    )
    import_parser.add_argument(
        "--no-snap-to-superflat",
        dest="snap_to_superflat",
        action="store_false",
        help="Disable superflat auto snap and use --y-offset directly.",
    )
    import_parser.add_argument(
        "--superflat-ground-y",
        type=int,
        default=-60,
        help="Superflat top surface Y level used for snap placement.",
    )
    import_parser.add_argument(
        "--ground-clearance",
        type=int,
        default=1,
        help="Blocks above superflat surface for model base when snapping.",
    )
    import_parser.add_argument(
        "--fixed-origin-x",
        type=int,
        default=0,
        help="Fixed placement X block origin when --origin-mode=fixed.",
    )
    import_parser.add_argument(
        "--fixed-origin-z",
        type=int,
        default=0,
        help="Fixed placement Z block origin when --origin-mode=fixed.",
    )
    import_parser.add_argument(
        "--dimension",
        default="minecraft:overworld",
        help="Minecraft dimension ID.",
    )
    import_parser.add_argument(
        "--game-platform",
        default="java",
        help="Minecraft platform for translation (java or bedrock).",
    )
    import_parser.add_argument(
        "--game-version",
        type=int,
        default=3700,
        help="Minecraft data version/integer version code.",
    )
    import_parser.add_argument(
        "--include-type",
        action="append",
        default=[],
        help="IFC type to include. Repeatable.",
    )
    import_parser.add_argument(
        "--exclude-type",
        action="append",
        default=[],
        help="IFC type to exclude. Repeatable.",
    )
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run validation and planning without writing blocks.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "import":
        config = ImportConfig(
            ifc_path=args.ifc,
            world_path=args.world,
            origin_mode=args.origin_mode,
            meters_per_block=args.meters_per_block,
            voxel_pitch_m=args.voxel_pitch_m,
            voxelize=args.voxelize,
            voxel_method=args.voxel_method,
            yaw_degrees=args.yaw_deg,
            y_offset=args.y_offset,
            snap_to_superflat=args.snap_to_superflat,
            superflat_ground_y=args.superflat_ground_y,
            ground_clearance=args.ground_clearance,
            fixed_origin_x=args.fixed_origin_x,
            fixed_origin_z=args.fixed_origin_z,
            dimension=args.dimension,
            game_platform=args.game_platform,
            game_version=args.game_version,
            include_types=tuple(args.include_type),
            exclude_types=tuple(args.exclude_type),
            block_map=default_block_map(),
        )
        return run_import(config, dry_run=args.dry_run)

    parser.error(f"Unsupported command: {args.command}")
    return 2
