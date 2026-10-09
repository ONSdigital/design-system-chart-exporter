"""StorageBackend: the structural interface every storage implementation meets.

A Protocol rather than an ABC: implementations (the boto3 S3 backend, the
in-memory fake in tests) need no inheritance or imports from this module —
anything with a matching ``put`` satisfies it, checked statically by mypy at
the point of use. With one method and no shared behaviour to inherit, an ABC
would only add coupling.

The interface is deliberately synchronous: boto3 is blocking, and async
offloading (run_in_threadpool) is the caller's concern in the service layer.
Implementations raise the domain StorageError; nothing here knows about HTTP.
"""

from typing import Protocol

from app.domain.models import StoredObject


class StorageBackend(Protocol):  # pylint: disable=too-few-public-methods
    """Persists rendered chart bytes under a key, privately."""

    def put(self, *, key: str, data: bytes, content_type: str) -> StoredObject:
        """Store bytes under key and return the stored object's metadata.

        Raises:
            StorageError: if the object could not be stored.
        """
