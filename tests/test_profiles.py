"""Profile schema checks plus decoding of payloads captured from hardware."""

from __future__ import annotations

from importlib.resources import files

import pytest

from lab_ble_mcp.codec import BleCodecError, build_field
from lab_ble_mcp.mock_backend import CAPTURED_PAYLOADS
from lab_ble_mcp.profile import (
    BleProfileError,
    available_profiles,
    build_profile,
    load_profile,
)


# Expected physical values for the payloads in CAPTURED_PAYLOADS. These were
# read off real devices on 2026-07-20 and are the reason the profiles exist.
OMRON_ADVERTISEMENT = {
    "temperature": 27.47,
    "humidity": 63.49,
    "illuminance": 45,
    "pressure": 1003.703,
    "sound_noise": 56.05,
    "etvoc": 0,
    "eco2": 400,
}
OMRON_GATT = {
    "temperature": 27.46,
    "humidity": 63.49,
    "illuminance": 45,
    "pressure": 1003.715,
    "sound_noise": 57.91,
    "etvoc": 0,
    "eco2": 403,
}
SWITCHBOT_ADVERTISEMENT = {"temperature": 28.3, "humidity": 49, "battery": 69}


def _decode(profile_name: str, mode: str) -> dict[str, float]:
    profile = load_profile(profile_name)
    source = profile.advertisement if mode == "advertisement" else profile.gatt
    assert source is not None
    payload = CAPTURED_PAYLOADS[profile_name][mode]
    return {field.name: field.decode(payload) for field in source.fields}


@pytest.mark.parametrize(
    ("profile_name", "mode", "expected"),
    [
        ("omron_2jcie", "advertisement", OMRON_ADVERTISEMENT),
        ("omron_2jcie", "gatt", OMRON_GATT),
        ("switchbot_meter", "advertisement", SWITCHBOT_ADVERTISEMENT),
    ],
)
def test_captured_payloads_decode_to_measured_values(profile_name, mode, expected):
    assert _decode(profile_name, mode) == pytest.approx(expected)


def test_omron_advertisement_and_gatt_paths_agree():
    """Two independent transports must report the same physical state.

    The captures are seconds apart, so slow-moving quantities should match
    closely while sound noise, which is genuinely dynamic, may differ.
    """
    advertisement = _decode("omron_2jcie", "advertisement")
    gatt = _decode("omron_2jcie", "gatt")
    assert advertisement["temperature"] == pytest.approx(gatt["temperature"], abs=0.1)
    assert advertisement["humidity"] == pytest.approx(gatt["humidity"], abs=0.1)
    assert advertisement["illuminance"] == gatt["illuminance"]
    assert advertisement["pressure"] == pytest.approx(gatt["pressure"], abs=0.05)


def test_bundled_profiles_load_and_declare_verified_support():
    names = available_profiles()
    assert {"omron_2jcie", "switchbot_meter"} <= names
    for name in names:
        profile = load_profile(name)
        assert profile.name == name
        assert profile.advertisement is not None or profile.gatt is not None
        assert profile.metadata["support_level"] in {
            "experimental",
            "mock_verified",
            "verified",
        }


def test_verified_profiles_are_backed_by_captured_payloads():
    """A profile may only claim ``verified`` if a real capture decodes with it."""
    for name in available_profiles():
        if load_profile(name).metadata["support_level"] == "verified":
            assert name in CAPTURED_PAYLOADS, name
            assert CAPTURED_PAYLOADS[name], name


def test_switchbot_declares_no_gatt_access():
    """The Meter broadcasts everything and refuses connections."""
    assert load_profile("switchbot_meter").gatt is None


def test_profiles_are_packaged_resources():
    for name in ("omron_2jcie", "switchbot_meter"):
        resource = files("lab_ble_mcp.profiles").joinpath(f"{name}.yaml")
        assert resource.is_file()
        assert "support_level:" in resource.read_text("utf-8")


def test_unknown_profile_fails_closed():
    with pytest.raises(BleProfileError, match="unknown BLE profile"):
        load_profile("no_such_profile")
    with pytest.raises(BleProfileError, match="invalid shape"):
        load_profile("../etc/passwd")
    with pytest.raises(BleProfileError, match="invalid shape"):
        load_profile("Omron")


def _document(**overrides):
    document = {
        "profile": "sample",
        "metadata": {
            "manufacturer": "ACME",
            "model": "S1",
            "support_level": "experimental",
            "definition_version": "0.1.0",
        },
        "access": {
            "advertisement": {
                "manufacturer_id": 0x1234,
                "fields": {
                    "temperature": {"offset": 0, "type": "i16le", "unit": "degC"}
                },
            }
        },
    }
    document.update(overrides)
    return document


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"profile": "other"}, "matching profile key"),
        ({"metadata": {}}, "must declare manufacturer"),
        ({"access": {}}, "non-empty access block"),
        ({"unexpected": 1}, "unknown keys"),
    ],
)
def test_malformed_profile_documents_are_rejected(overrides, match):
    with pytest.raises(BleProfileError, match=match):
        build_profile("sample", _document(**overrides))


def test_support_level_must_come_from_the_declared_set():
    document = _document()
    document["metadata"]["support_level"] = "production"
    with pytest.raises(BleProfileError, match="support_level must be one of"):
        build_profile("sample", document)


def test_advertisement_needs_exactly_one_payload_source():
    for advertisement in (
        {"fields": {"t": {"offset": 0, "type": "u8", "unit": "degC"}}},
        {
            "manufacturer_id": 1,
            "service_uuid": "0000fd3d-0000-1000-8000-00805f9b34fb",
            "fields": {"t": {"offset": 0, "type": "u8", "unit": "degC"}},
        },
    ):
        with pytest.raises(BleProfileError, match="exactly one"):
            build_profile("sample", _document(access={"advertisement": advertisement}))


@pytest.mark.parametrize(
    ("spec", "match"),
    [
        ({"offset": 0, "type": "u8"}, "non-empty unit"),
        ({"offset": 0, "type": "f64", "unit": "degC"}, "must declare a type"),
        ({"offset": -1, "type": "u8", "unit": "degC"}, "non-negative integer offset"),
        ({"type": "u8", "unit": "degC"}, "non-negative integer offset"),
        ({"decoder": "no_such_decoder", "unit": "degC"}, "unknown decoder"),
        (
            {"decoder": "switchbot_temp_c", "offset": 0, "unit": "degC"},
            "must not also",
        ),
        ({"offset": 0, "type": "u8", "unit": "degC", "extra": 1}, "unknown keys"),
    ],
)
def test_malformed_field_specs_are_rejected(spec, match):
    with pytest.raises(BleCodecError, match=match):
        build_field("temperature", spec)


def test_short_payloads_are_rejected_rather_than_padded():
    field = build_field("pressure", {"offset": 8, "type": "i32le", "unit": "hPa"})
    with pytest.raises(BleCodecError, match="needs 12 bytes"):
        field.decode(bytes(11))


def test_switchbot_decoder_handles_the_sign_bit():
    from lab_ble_mcp.codec import CUSTOM_DECODERS

    decoder = CUSTOM_DECODERS["switchbot_temp_c"]
    assert decoder(bytes.fromhex("5400c5039c31")) == pytest.approx(28.3)
    # Same magnitude with bit 7 of byte 4 cleared means a negative reading.
    assert decoder(bytes.fromhex("5400c5031c31")) == pytest.approx(-28.3)
    with pytest.raises(BleCodecError, match="at least 6 bytes"):
        decoder(bytes(5))
