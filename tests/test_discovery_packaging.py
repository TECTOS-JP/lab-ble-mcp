from __future__ import annotations

from importlib import metadata
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib

import pytest

from lab_executor.backends import BackendRegistration, discover_backends

from lab_backend_template.backend import EchoBackend
from lab_backend_template.discovery import make_backend


ROOT = Path(__file__).parents[1]


def _installed_echo_entry_points():
    matches = [
        entry_point
        for entry_point in metadata.entry_points(group="lab_executor.backends")
        if entry_point.name == "echo"
    ]
    if not matches:
        pytest.skip(
            "lab-backend-template installation metadata is required for entry-point tests"
        )
    return matches


def test_factory_returns_strict_echo_registration():
    registration = make_backend(
        {"resources": ["ECHO::one"], "initial_values": {"value": "7"}}
    )
    assert isinstance(registration, BackendRegistration)
    assert isinstance(registration.backend, EchoBackend)
    assert registration.prefixes == ("ECHO::",)


def test_factory_rejects_unknown_or_malformed_config():
    with pytest.raises(ValueError, match="unknown"):
        make_backend({"raw_write": True})
    with pytest.raises(TypeError):
        make_backend({"resources": "ECHO::one"})
    with pytest.raises(TypeError):
        make_backend({"initial_values": []})
    with pytest.raises(TypeError):
        make_backend([])  # type: ignore[arg-type]


def test_installed_entry_point_discovers_factory():
    matches = _installed_echo_entry_points()
    assert len(matches) == 1
    assert matches[0].load() is make_backend


def test_bef_discovery_constructs_installed_echo_backend():
    _installed_echo_entry_points()
    registrations = discover_backends(["echo"])
    assert len(registrations) == 1
    assert isinstance(registrations[0].backend, EchoBackend)
    assert registrations[0].prefixes == ("ECHO::",)


def test_pyproject_has_frozen_packaging_metadata_and_sdist_allowlist():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    project = data["project"]
    assert project["name"] == "lab-backend-template"
    assert project["version"] == "0.1.0"
    assert "lab-executor-mcp>=2.35.0,<3.0.0" in project["dependencies"]
    assert project["license-files"] == ["LICENSE"]
    assert set(project["urls"]) >= {"Homepage", "Repository", "Changelog", "Issues"}
    assert project["entry-points"]["lab_executor.backends"]["echo"] == (
        "lab_backend_template.discovery:make_backend"
    )
    include = data["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert include and all(item.startswith("/") for item in include)
    assert {"/src/lab_backend_template", "/tests", "/docs", "/conftest.py"} <= set(
        include
    )
    assert "/.gitignore" in include
