"""BLE backend for lab-executor-mcp: environment sensors plus BiTalino streaming."""

from lab_ble_mcp.backend import (
    BleBackend,
    BleBackendError,
    BleTransportError,
    BleWriteRejected,
)
from lab_ble_mcp.mock_backend import MockBleBackend
from lab_ble_mcp.profile import Profile, available_profiles, load_profile

__version__ = "0.2.0"

__all__ = [
    "BleBackend",
    "BleBackendError",
    "BleTransportError",
    "BleWriteRejected",
    "MockBleBackend",
    "Profile",
    "__version__",
    "available_profiles",
    "load_profile",
]
