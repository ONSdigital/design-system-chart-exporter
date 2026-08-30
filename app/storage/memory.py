"""In-memory storage fake for tests.

Satisfies the StorageBackend Protocol structurally (the explicit annotation
in tests catches drift). Includes a fault-injection hook: set ``fail_with``
to make the next put raise, for exercising the 500 storage error path.
"""

from dataclasses import dataclass

from app.domain.models import StoredObject


@dataclass(frozen=True, slots=True)
class MemoryObject:
    """What the fake remembers about one stored object."""

    data: bytes
    content_type: str


class MemoryStorageBackend:  # pylint: disable=too-few-public-methods
    """Dict-backed StorageBackend for API tests. Not thread-safe; tests only."""

    def __init__(self, *, bucket: str = "memory-bucket", fail_with: Exception | None = None) -> None:
        self.bucket = bucket
        self.objects: dict[str, MemoryObject] = {}
        self.fail_with = fail_with

    def put(self, *, key: str, data: bytes, content_type: str) -> StoredObject:
        """Store the bytes in the dict, or raise the injected fault."""
        if self.fail_with is not None:
            raise self.fail_with
        self.objects[key] = MemoryObject(data=data, content_type=content_type)

        return StoredObject(bucket=self.bucket, key=key, size_bytes=len(data), content_type=content_type)
