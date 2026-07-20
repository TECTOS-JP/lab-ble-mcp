from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import yaml
from lab_executor.models.instrument_def import InstrumentDefinition


ROOT = Path(__file__).parents[1]
DEFINITION = (
    ROOT / "src" / "lab_backend_template" / "builtin_instruments" / "echo_example.yaml"
)


def _raw_definition() -> dict:
    return yaml.safe_load(DEFINITION.read_text("utf-8"))


def test_builtin_definition_is_valid_safe_and_not_verified():
    raw = _raw_definition()
    definition = InstrumentDefinition(**raw)
    assert definition.metadata.support_level == "experimental"
    assert definition.metadata.support_level != "verified"
    assert "hardware has not been verified" in definition.metadata.description.lower()
    assert raw["safe_shutdown"] == [{"command": "set_safe_value"}]
    for name, command in raw["commands"].items():
        if command["type"] != "write":
            continue
        for parameter in command.get("parameters", []):
            assert "range" in parameter, f"{name}.{parameter['name']} lacks range"


def test_builtin_definition_is_packaged_resource():
    resource = files("lab_backend_template.builtin_instruments").joinpath(
        "echo_example.yaml"
    )
    assert resource.is_file()
    assert 'support_level: "experimental"' in resource.read_text("utf-8")


def test_template_guide_has_six_steps_and_grep_identifiers():
    text = (ROOT / "docs" / "USING_THIS_TEMPLATE.md").read_text("utf-8")
    for step in range(1, 7):
        assert f"## {step}." in text
    for identifier in ("lab_backend_template", "lab-backend-template", "ECHO::"):
        assert identifier in text


def test_ci_has_required_jobs_actions_and_dependency_modes():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    data = yaml.safe_load(text)
    assert {
        "unit",
        "latest-release-integration",
        "main-compatibility-smoke",
        "build",
    } <= set(data["jobs"])
    assert data["jobs"]["main-compatibility-smoke"]["continue-on-error"] is True
    assert "actions/checkout@v5" in text
    assert "actions/setup-python@v6" in text
    assert 'python-version: "3.11"' in text
    assert "ruff check" in text and "ruff format --check" in text
    assert "BEF conformance kit" in text
    assert "git+https://github.com/TECTOS-JP/lab-executor-mcp@main" in text
    release_job = yaml.safe_dump(data["jobs"]["latest-release-integration"])
    assert "git+" not in release_job


def test_publish_uses_oidc_testpypi_and_strict_sdist_guard():
    text = (ROOT / ".github" / "workflows" / "publish.yml").read_text("utf-8")
    data = yaml.safe_load(text)
    for required in (
        "actions/checkout@v5",
        "actions/setup-python@v6",
        "actions/upload-artifact@v6",
        "actions/download-artifact@v7",
        "id-token: write",
        "repository-url: https://test.pypi.org/legacy/",
        "twine check",
        "allowed_roots",
    ):
        assert required in text
    assert data["jobs"]["publish-testpypi"]["if"] == (
        "github.event_name == 'workflow_dispatch'"
    )
    assert data["jobs"]["publish-pypi"]["if"] == "github.event_name == 'push'"


def test_repository_text_files_use_lf_only():
    suffixes = {".py", ".toml", ".yaml", ".yml", ".md", ".txt"}
    generated = {".git", ".pytest_cache", ".ruff_cache", ".venv", "dist", "build"}
    for path in ROOT.rglob("*"):
        if (
            path.is_file()
            and path.suffix in suffixes
            and not generated.intersection(path.parts)
        ):
            assert b"\r\n" not in path.read_bytes(), path
