from __future__ import annotations

import pytest

from ifc2mc.cli import (
    _parse_block_map_overrides,
    _parse_type_priority_overrides,
    build_parser,
    main,
)
from ifc2mc.config import default_block_map, default_type_priority


def test_parse_block_map_overrides_valid() -> None:
    parsed = _parse_block_map_overrides(
        [
            "IfcWall=minecraft:stone",
            "IfcColumn=stone_bricks",
            "IfcWall=minecraft:smooth_stone",
        ]
    )
    assert parsed == {
        "IfcWall": "minecraft:smooth_stone",
        "IfcColumn": "stone_bricks",
    }


@pytest.mark.parametrize(
    "entry",
    ["", "IfcWall", "=minecraft:stone", "IfcWall="],
)
def test_parse_block_map_overrides_invalid(entry: str) -> None:
    with pytest.raises(ValueError):
        _parse_block_map_overrides([entry])


def test_parse_type_priority_overrides_valid() -> None:
    parsed = _parse_type_priority_overrides(
        ["IfcWall=10", "IfcBeam=50", "IfcWall=70"]
    )
    assert parsed == {"IfcWall": 70, "IfcBeam": 50}


@pytest.mark.parametrize(
    "entry",
    ["", "IfcWall", "=5", "IfcWall=", "IfcWall=abc"],
)
def test_parse_type_priority_overrides_invalid(entry: str) -> None:
    with pytest.raises(ValueError):
        _parse_type_priority_overrides([entry])


def test_import_parser_accepts_type_priority_args() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "import",
            "--ifc",
            "model.ifc",
            "--world",
            "world",
            "--type-priority",
            "IfcWall=11",
            "--clear-default-type-priority",
        ]
    )
    assert args.type_priority == ["IfcWall=11"]
    assert args.clear_default_type_priority is True


def test_import_parser_accepts_block_map_args() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "import",
            "--ifc",
            "model.ifc",
            "--world",
            "world",
            "--block-map",
            "IfcWall=minecraft:stone",
            "--clear-default-block-map",
        ]
    )
    assert args.block_map == ["IfcWall=minecraft:stone"]
    assert args.clear_default_block_map is True


def test_main_rejects_invalid_block_map() -> None:
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "import",
                "--ifc",
                "model.ifc",
                "--world",
                "world",
                "--block-map",
                "IfcWall",
                "--dry-run",
            ]
        )
    assert exc.value.code == 2


def test_main_rejects_invalid_type_priority() -> None:
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "import",
                "--ifc",
                "model.ifc",
                "--world",
                "world",
                "--type-priority",
                "IfcWall",
                "--dry-run",
            ]
        )
    assert exc.value.code == 2


def test_main_merges_default_and_override_type_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_import(config, *, dry_run: bool) -> int:
        captured["config"] = config
        captured["dry_run"] = dry_run
        return 0

    monkeypatch.setattr("ifc2mc.cli.run_import", fake_run_import)

    rc = main(
        [
            "import",
            "--ifc",
            "model.ifc",
            "--world",
            "world",
            "--type-priority",
            "IfcWall=999",
            "--dry-run",
        ]
    )
    assert rc == 0
    assert captured["dry_run"] is True
    cfg = captured["config"]
    assert cfg.type_priority["IfcWall"] == 999
    assert cfg.type_priority["IfcFooting"] == default_type_priority()["IfcFooting"]


def test_main_merges_default_and_override_block_map(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_import(config, *, dry_run: bool) -> int:
        captured["config"] = config
        captured["dry_run"] = dry_run
        return 0

    monkeypatch.setattr("ifc2mc.cli.run_import", fake_run_import)

    rc = main(
        [
            "import",
            "--ifc",
            "model.ifc",
            "--world",
            "world",
            "--block-map",
            "IfcWall=minecraft:stone",
            "--dry-run",
        ]
    )
    assert rc == 0
    cfg = captured["config"]
    assert cfg.block_map["IfcWall"] == "minecraft:stone"
    assert cfg.block_map["IfcBeam"] == default_block_map()["IfcBeam"]


def test_main_clears_default_block_map_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run_import(config, *, dry_run: bool) -> int:
        captured["config"] = config
        captured["dry_run"] = dry_run
        return 0

    monkeypatch.setattr("ifc2mc.cli.run_import", fake_run_import)

    rc = main(
        [
            "import",
            "--ifc",
            "model.ifc",
            "--world",
            "world",
            "--clear-default-block-map",
            "--block-map",
            "IfcWall=minecraft:stone",
            "--dry-run",
        ]
    )
    assert rc == 0
    cfg = captured["config"]
    assert cfg.block_map == {"IfcWall": "minecraft:stone"}


def test_main_clears_default_type_priority_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run_import(config, *, dry_run: bool) -> int:
        captured["config"] = config
        captured["dry_run"] = dry_run
        return 0

    monkeypatch.setattr("ifc2mc.cli.run_import", fake_run_import)

    rc = main(
        [
            "import",
            "--ifc",
            "model.ifc",
            "--world",
            "world",
            "--clear-default-type-priority",
            "--type-priority",
            "IfcWall=21",
            "--dry-run",
        ]
    )
    assert rc == 0
    cfg = captured["config"]
    assert cfg.type_priority == {"IfcWall": 21}
