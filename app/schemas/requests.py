"""Request models for the charts API."""

from typing import Any, Literal

from pydantic import BaseModel, field_validator


class ChartRenderRequest(BaseModel):
    """Body of POST /charts.

    chart_config is an opaque vendor payload owned by the Design System
    contract (camelCase, Highcharts-derived). We validate only that it is a
    non-empty object — never its internal fields, so the contract can evolve
    without changes here.
    """

    language: Literal["en"]
    device: Literal["desktop"]
    chart_config: dict[str, Any]

    @field_validator("chart_config")
    @classmethod
    def chart_config_must_not_be_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Reject an empty chart_config object."""
        if not value:
            raise ValueError("chart_config must not be empty")
        return value
