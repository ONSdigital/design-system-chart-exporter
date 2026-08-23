"""Domain models returned by services to the route layer."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RenderedChart:
    """Object metadata of a chart that has been rendered and stored."""

    id: UUID
    key: str
    size_bytes: int
    width: int
    height: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Metadata of an object persisted by a storage backend."""

    bucket: str
    key: str
    size_bytes: int
    content_type: str
