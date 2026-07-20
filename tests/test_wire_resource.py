from __future__ import annotations

import pytest

from lab_ble_mcp.resource import BleResourceError, parse_resource_name
from lab_ble_mcp.wire import BleWireError, parse_wire_command


VALID = "BLE::omron_2jcie/D0:ED:3E:53:EE:22"


def test_valid_resource_splits_into_profile_and_address():
    parsed = parse_resource_name(VALID)
    assert parsed.profile == "omron_2jcie"
    assert parsed.address == "D0:ED:3E:53:EE:22"


@pytest.mark.parametrize(
    "resource",
    [
        "",
        "BLE::",
        "BLE::omron_2jcie",
        "BLE::omron_2jcie/",
        "BLE::/D0:ED:3E:53:EE:22",
        "BLE::omron_2jcie/D0:ED:3E:53:EE",
        "BLE::omron_2jcie/D0-ED-3E-53-EE-22",
        "BLE::omron_2jcie/d0:ed:3e:53:ee:22",
        "BLE::OMRON_2JCIE/D0:ED:3E:53:EE:22",
        "ble::omron_2jcie/D0:ED:3E:53:EE:22",
        "GPIB0::1::INSTR",
        " BLE::omron_2jcie/D0:ED:3E:53:EE:22",
        "BLE::omron_2jcie/D0:ED:3E:53:EE:22 ",
        "BLE::omron_2jcie/D0:ED:3E:53:EE:22\n",
        "BLE::omron 2jcie/D0:ED:3E:53:EE:22",
    ],
)
def test_malformed_resources_are_rejected(resource):
    with pytest.raises(BleResourceError):
        parse_resource_name(resource)


def test_non_string_resource_is_rejected():
    with pytest.raises(BleResourceError):
        parse_resource_name(None)  # type: ignore[arg-type]


def test_lowercase_address_is_not_silently_normalized():
    """One address must have exactly one spelling in bundles and logs."""
    with pytest.raises(BleResourceError):
        parse_resource_name("BLE::omron_2jcie/d0:ed:3e:53:ee:22")


@pytest.mark.parametrize("command", ["READ temperature", "INFO model"])
def test_valid_commands_parse_as_reads(command):
    parsed = parse_wire_command(command)
    assert parsed.is_read


@pytest.mark.parametrize(
    "command",
    [
        "",
        "READ",
        "INFO",
        "READ temperature extra",
        "READ Temperature",
        "READ 1temperature",
        "READ temp/erature",
        "read temperature",
        "READ  temperature",
        " READ temperature",
        "READ temperature ",
        "READ temperature\n",
        "*IDN?",
        "CONF",
    ],
)
def test_malformed_commands_are_rejected(command):
    with pytest.raises(BleWireError):
        parse_wire_command(command)


@pytest.mark.parametrize(
    "command",
    ["WRITE temperature 20", "SET temperature 20", "PAIR", "DFU start"],
)
def test_the_grammar_cannot_express_a_write(command):
    """No write opcode exists, so threshold and DFU characteristics are unreachable."""
    with pytest.raises(BleWireError, match="unknown BLE opcode"):
        parse_wire_command(command)


def test_non_string_command_is_rejected():
    with pytest.raises(BleWireError):
        parse_wire_command(None)  # type: ignore[arg-type]
