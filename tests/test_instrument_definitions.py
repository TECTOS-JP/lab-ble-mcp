"""Instrument definitions in the ecosystem schema, and their link to profiles.

Two documents describe each device: an instrument definition declaring named
commands, and a profile declaring byte layout. They are written by hand and
can drift apart, so the tests below tie them together rather than trusting
that whoever edited one remembered the other.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import pytest
import yaml
from lab_executor.models.instrument_def import InstrumentDefinition

from lab_ble_mcp.profile import available_profiles, load_profile
from lab_ble_mcp.wire import parse_wire_command


ROOT = Path(__file__).parents[1]
DEFINITIONS_DIR = ROOT / "src" / "lab_ble_mcp" / "builtin_instruments"
ECOSYSTEM_SUPPORT_LEVELS = {"verified", "tested", "experimental", "draft"}


def _definition_names() -> list[str]:
    return sorted(path.stem for path in DEFINITIONS_DIR.glob("*.yaml"))


def _raw(name: str) -> dict:
    return yaml.safe_load((DEFINITIONS_DIR / f"{name}.yaml").read_text("utf-8"))


def _definition(name: str) -> InstrumentDefinition:
    return InstrumentDefinition(**_raw(name))


def test_every_profile_has_an_instrument_definition():
    """A profile without a definition is invisible to list_commands."""
    assert set(_definition_names()) == set(available_profiles())


@pytest.mark.parametrize("name", _definition_names())
def test_definition_validates_against_the_ecosystem_model(name):
    definition = _definition(name)
    assert definition.metadata.manufacturer
    assert definition.metadata.model
    assert definition.commands


@pytest.mark.parametrize("name", _definition_names())
def test_support_level_uses_the_ecosystem_vocabulary(name):
    definition = _definition(name)
    assert definition.metadata.support_level in ECOSYSTEM_SUPPORT_LEVELS


@pytest.mark.parametrize("name", _definition_names())
def test_definition_and_profile_agree_on_support_level(name):
    assert (
        _definition(name).metadata.support_level
        == (load_profile(name).metadata["support_level"])
    )


@pytest.mark.parametrize("name", _definition_names())
def test_verified_definitions_carry_validation_evidence(name):
    """Strict validation rejects a ``verified`` claim with no evidence."""
    definition = _definition(name)
    if definition.metadata.support_level != "verified":
        return
    evidence = definition.metadata.validation_evidence
    assert {"tested_by", "tested_at", "interface", "tested_items"} <= set(evidence)
    assert evidence["tested_items"]


@pytest.mark.parametrize("name", _definition_names())
def test_every_command_string_parses_with_the_wire_grammar(name):
    """A command the backend cannot parse would fail only at execution time."""
    for command_name, command in _definition(name).commands.items():
        assert command.type == "query", f"{name}.{command_name} is not a query"
        parsed = parse_wire_command(command.scpi)
        assert parsed.is_read


@pytest.mark.parametrize("name", _definition_names())
def test_read_commands_cover_exactly_the_profile_measurands(name):
    profile = load_profile(name)
    declared = {
        parse_wire_command(command.scpi).name
        for command in _definition(name).commands.values()
        if command.scpi.startswith("READ ")
    }
    assert declared == set(profile.measurands)


@pytest.mark.parametrize("name", _definition_names())
def test_state_query_entries_reference_real_commands_and_units(name):
    definition = _definition(name)
    for measurand, item in definition.state_query.items():
        assert item.command in definition.commands, measurand
        assert item.unit
        assert definition.commands[item.command].returns.unit == item.unit


@pytest.mark.parametrize("name", _definition_names())
def test_no_definition_declares_a_write_command(name):
    """The read-only guarantee must hold at the definition layer too."""
    for command_name, command in _definition(name).commands.items():
        assert command.type != "write", f"{name}.{command_name} declares a write"
        assert not command.parameters, f"{name}.{command_name} takes parameters"


@pytest.mark.parametrize("name", _definition_names())
def test_safe_shutdown_is_empty_because_there_is_no_actuation(name):
    """A measurement-only device has nothing to return to a safe state."""
    assert _definition(name).safe_shutdown == []
    assert "safe_shutdown: []" in (DEFINITIONS_DIR / f"{name}.yaml").read_text("utf-8")


@pytest.mark.parametrize("name", _definition_names())
def test_timeout_accounts_for_advertisement_intervals(name):
    """The ecosystem default of 5000 ms is too short for a cold BLE read."""
    assert _definition(name).connection.default_timeout_ms >= 20000


@pytest.mark.parametrize("name", _definition_names())
def test_definitions_are_packaged_resources(name):
    resource = files("lab_ble_mcp.builtin_instruments").joinpath(f"{name}.yaml")
    assert resource.is_file()
    assert "support_level:" in resource.read_text("utf-8")
