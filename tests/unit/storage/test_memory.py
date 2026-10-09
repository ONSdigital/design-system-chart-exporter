import pytest

from app.domain.exceptions import StorageError
from app.domain.models import StoredObject
from app.storage.base import StorageBackend
from app.storage.memory import MemoryStorageBackend

# The annotation makes mypy/IDEs verify the fake satisfies the Protocol
_PROTOCOL_CHECK: StorageBackend = MemoryStorageBackend()


def test_put_stores_bytes_and_returns_metadata():
    backend = MemoryStorageBackend(bucket="test-bucket")

    stored = backend.put(key="charts/abc.png", data=b"png-bytes", content_type="image/png")

    assert stored == StoredObject(bucket="test-bucket", key="charts/abc.png", size_bytes=9, content_type="image/png")
    assert backend.objects["charts/abc.png"].data == b"png-bytes"
    assert backend.objects["charts/abc.png"].content_type == "image/png"


def test_fault_injection_raises_and_stores_nothing():
    backend = MemoryStorageBackend(fail_with=StorageError("injected"))

    with pytest.raises(StorageError, match="injected"):
        backend.put(key="charts/abc.png", data=b"x", content_type="image/png")

    assert backend.objects == {}
