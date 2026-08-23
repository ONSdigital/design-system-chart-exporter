"""Response models for the charts API, matching the agreed API spec."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ChartObjectResponse(BaseModel):
    """201 response body: metadata of the stored chart object."""

    id: UUID
    created_at: datetime
    bucket: str
    key: str
    content_type: str
    size_bytes: int
    width: int
    height: int


class ErrorItem(BaseModel):
    """A single error in the spec's error document."""

    code: str
    description: str


class ErrorDocument(BaseModel):
    """Envelope returned by every non-2xx response."""

    errors: list[ErrorItem]
