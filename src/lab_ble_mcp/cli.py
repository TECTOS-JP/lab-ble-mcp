"""Thin CLI wrapper around the public lab-executor server contract."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Sequence

from lab_executor.control_plane import run_mcp_with_control
from lab_executor.server import compose_server

from lab_ble_mcp.backend import BleBackend
from lab_ble_mcp.profile import available_profiles


def _control_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("control port must be an integer") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("control port must be between 0 and 65535")
    return port


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lab-ble",
        description="Serve BLE environment sensors through the public lab-executor API.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="serve the BLE backend over MCP stdio")
    serve.add_argument(
        "--resource",
        action="append",
        required=True,
        help="configured BLE::<profile>/<ADDRESS> resource (repeat for multiple)",
    )
    serve.add_argument("--dry-run", action="store_true", help="compose and list tools")
    serve.add_argument(
        "--control-port",
        type=_control_port,
        default=0,
        help="localhost control-plane port (default: 0, OS-assigned)",
    )
    subparsers.add_parser("profiles", help="list bundled device profiles")
    return parser


async def _dry_run(mcp: object, backend: BleBackend) -> None:
    list_tools = getattr(mcp, "list_tools")
    tools = await list_tools()
    payload = {
        "backend_id": backend.backend_id,
        "resources": await backend.list_resources(),
        "tools": sorted(tool.name for tool in tools),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "profiles":
        for name in sorted(available_profiles()):
            print(name)
        return 0
    try:
        backend = BleBackend(resources=args.resource)
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    mcp, job_mgr = compose_server(backend, name="lab-ble-mcp")
    try:
        if args.dry_run:
            asyncio.run(_dry_run(mcp, backend))
        else:
            asyncio.run(
                run_mcp_with_control(
                    mcp,
                    job_mgr,
                    args.control_port,
                    backend_id=backend.backend_id,
                )
            )
    finally:
        backend.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
