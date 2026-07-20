from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


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


def test_no_template_identifiers_remain():
    """The rename must be complete; a stray identifier means a missed step."""
    stale = ("lab_backend_template", "lab-backend-template", "ECHO::")
    suffixes = {".py", ".toml", ".yaml", ".yml", ".md"}
    generated = {".git", ".pytest_cache", ".ruff_cache", ".venv", "dist", "build"}
    this_file = Path(__file__).resolve()
    for path in ROOT.rglob("*"):
        if (
            path.is_file()
            and path.suffix in suffixes
            and path.resolve() != this_file  # the identifiers appear here as literals
            and not generated.intersection(path.parts)
        ):
            text = path.read_text("utf-8")
            for identifier in stale:
                assert identifier not in text, f"{path} still mentions {identifier}"


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
