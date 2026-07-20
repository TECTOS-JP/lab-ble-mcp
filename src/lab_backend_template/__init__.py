"""Working Echo backend example for lab-executor-mcp."""

from lab_backend_template.backend import EchoBackend, EchoBackendError, EchoKeyError
from lab_backend_template.mock_backend import MockEchoBackend

__version__ = "0.1.0"

__all__ = [
    "EchoBackend",
    "EchoBackendError",
    "EchoKeyError",
    "MockEchoBackend",
    "__version__",
]
