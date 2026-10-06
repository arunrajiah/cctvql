"""
Keep Home Assistant translation files in sync with strings.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

HA_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "cctvql"
STRINGS = HA_DIR / "strings.json"
TRANSLATIONS = sorted((HA_DIR / "translations").glob("*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _key_paths(obj: dict, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, value in obj.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            paths |= _key_paths(value, full)
        else:
            paths.add(full)
    return paths


def test_translation_files_exist():
    assert STRINGS.exists()
    assert TRANSLATIONS, "no translation files found"


def test_en_matches_strings_exactly():
    assert _load(HA_DIR / "translations" / "en.json") == _load(STRINGS)


@pytest.mark.parametrize("path", TRANSLATIONS, ids=[p.stem for p in TRANSLATIONS])
def test_translation_has_same_keys_as_strings(path: Path):
    expected = _key_paths(_load(STRINGS))
    actual = _key_paths(_load(path))
    assert actual == expected, (
        f"{path.name}: missing {sorted(expected - actual)}, extra {sorted(actual - expected)}"
    )


@pytest.mark.parametrize("path", TRANSLATIONS, ids=[p.stem for p in TRANSLATIONS])
def test_translation_values_are_non_empty_strings(path: Path):
    def check(obj: dict, prefix: str = "") -> None:
        for key, value in obj.items():
            full = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                check(value, full)
            else:
                assert isinstance(value, str) and value.strip(), f"{path.name}: empty {full}"

    check(_load(path))
