from __future__ import annotations

import pytest

from ifc2mc.cli import _parse_type_priority_overrides, build_parser, main


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
