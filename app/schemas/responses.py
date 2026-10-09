"""Response models for the charts API, matching the agreed API spec."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field


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

    # Bounded so the published schema declares maxItems (an unbounded array is
    # flagged by API linters). In practice at most a handful of items appear:
    # validation errors are deduplicated to the distinct field codes.
    errors: Annotated[list[ErrorItem], Field(max_length=50)]
