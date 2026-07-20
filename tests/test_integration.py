from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from lab_executor.backends import (
    BackendRegistration,
    CompositeBackend,
    ResourceRoutingError,
)

from lab_ble_mcp.cli import main
from lab_ble_mcp.mock_backend import DEFAULT_MOCK_RESOURCE, MockBleBackend


ROOT = Path(__file__).parents[1]


class OtherBackend:
    backend_id = "other"

    async def list_resources(self) -> list[str]:
        return ["OTHER::1"]

    async def query(self, resource_name: str, command: str, **_kwargs) -> str:
        return f"{resource_name}:{command}"

    async def write(self, resource_name: str, command: str, **_kwargs) -> None:
        self.last_write = (resource_name, command)

    def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_composite_routes_ble_and_rejects_unmatched_resource():
    ble = MockBleBackend()
    composite = CompositeBackend(
        [
            BackendRegistration(backend=ble, prefixes=("BLE::",)),
            BackendRegistration(backend=OtherBackend(), prefixes=("OTHER::",)),
        ]
    )
    assert await composite.query(DEFAULT_MOCK_RESOURCE, "READ temperature") == "27.47"
    assert await composite.query("OTHER::1", "PING") == "OTHER::1:PING"
    with pytest.raises(ResourceRoutingError):
        await composite.query("UNKNOWN::1", "PING")


def test_cli_dry_run_composes_server_and_lists_tools(capsys):
    assert main(["serve", "--resource", DEFAULT_MOCK_RESOURCE, "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backend_id"] == "ble"
    assert payload["resources"] == [DEFAULT_MOCK_RESOURCE]
    assert {"execute_named_command", "start_recipe_job"} <= set(payload["tools"])


def test_cli_lists_bundled_profiles(capsys):
    assert main(["profiles"]) == 0
    names = capsys.readouterr().out.split()
    assert {"omron_2jcie", "switchbot_meter"} <= set(names)


def test_cli_rejects_a_malformed_resource(capsys):
    with pytest.raises(SystemExit):
        main(["serve", "--resource", "BLE::bad", "--dry-run"])


def test_cli_imports_only_public_lab_executor_contract_modules():
    tree = ast.parse((ROOT / "src" / "lab_ble_mcp" / "cli.py").read_text("utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("lab_executor")
    }
    assert modules == {"lab_executor.control_plane", "lab_executor.server"}


def test_backend_module_does_not_import_bleak_at_module_scope():
    """Importing the package, or running a mock, must not touch a Bluetooth stack."""
    tree = ast.parse((ROOT / "src" / "lab_ble_mcp" / "backend.py").read_text("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
            )
            if any(name.split(".")[0] == "bleak" for name in names):
                assert node.col_offset > 0, "bleak must be imported lazily"
