"""Shared version metadata must stay consistent (roadmap Sprint 1, task 6)."""

import tomllib
from pathlib import Path

import trendbot


def test_package_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["project"]["version"] == trendbot.__version__
