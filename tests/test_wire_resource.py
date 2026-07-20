from __future__ import annotations

import pytest

from lab_backend_template.resource import EchoResourceError, parse_resource_name
from lab_backend_template.wire import EchoWireError, parse_wire_command


@pytest.mark.parametrize("resource", ["ECHO::demo", "ECHO::A-1", "ECHO::rack.unit_2"])
def test_resource_parser_accepts_exact_valid_names(resource):
    parsed = parse_resource_name(resource)
    assert parsed.name == resource.removeprefix("ECHO::")


@pytest.mark.parametrize(
    "resource",
    [
        "",
        "ECHO::",
        "echo::demo",
        " ECHO::demo",
        "ECHO::demo ",
        "ECHO::two::parts",
        "ECHO::bad name",
        "ECHO::/path",
        "OTHER::demo",
        "ECHO::" + "x" * 65,
    ],
)
def test_resource_parser_rejects_every_unknown_shape(resource):
    with pytest.raises(EchoResourceError):
        parse_resource_name(resource)


def test_wire_parser_accepts_get_and_set():
    get = parse_wire_command("GET temperature")
    assert get.is_read and not get.is_write and get.value is None
    set_command = parse_wire_command("SET temperature 25.5")
    assert set_command.is_write and set_command.key == "temperature"
    assert set_command.value == "25.5"


@pytest.mark.parametrize(
    "command",
    [
        "",
        "READ key",
        "get key",
        "GET",
        "GET key extra",
        "SET key",
        "SET key value extra",
        " SET key value",
        "SET  key value",
        "SET key ",
        "GET bad/key",
        "GET key\nSET key value",
        "SET key value with spaces",
        "SET key value\u3000with-space",
        "SET key café",
    ],
)
def test_wire_parser_fails_closed_for_unknown_or_malformed_commands(command):
    with pytest.raises(EchoWireError):
        parse_wire_command(command)
