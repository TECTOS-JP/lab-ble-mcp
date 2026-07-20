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

from lab_backend_template.cli import main
from lab_backend_template.mock_backend import MockEchoBackend


ROOT = Path(__file__).parents[1]
RESOURCE = "ECHO::demo"


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
async def test_composite_routes_echo_and_rejects_unmatched_resource():
    echo = MockEchoBackend(resources=[RESOURCE], initial_values={"value": "4"})
    other = OtherBackend()
    composite = CompositeBackend(
        [
            BackendRegistration(backend=echo, prefixes=("ECHO::",)),
            BackendRegistration(backend=other, prefixes=("OTHER::",)),
        ]
    )
    assert await composite.query(RESOURCE, "GET value") == "4"
    assert await composite.query("OTHER::1", "PING") == "OTHER::1:PING"
    with pytest.raises(ResourceRoutingError):
        await composite.query("UNKNOWN::1", "PING")


def test_cli_dry_run_composes_server_and_lists_tools(capsys):
    assert main(["serve", "--resource", RESOURCE, "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backend_id"] == "echo"
    assert payload["resources"] == [RESOURCE]
    assert len(payload["tools"]) > 0
    assert {"execute_named_command", "start_recipe_job"} <= set(payload["tools"])


def test_cli_imports_only_public_lab_executor_contract_modules():
    tree = ast.parse(
        (ROOT / "src" / "lab_backend_template" / "cli.py").read_text("utf-8")
    )
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("lab_executor")
    }
    assert modules == {"lab_executor.control_plane", "lab_executor.server"}
