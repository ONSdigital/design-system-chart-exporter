"""POST /charts: synchronously render a chart config and store the PNG."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import ChartExporter, get_chart_exporter, require_json_content_type
from app.config import Settings, get_settings
from app.logging import get_logger
from app.schemas.requests import ChartRenderRequest
from app.schemas.responses import ChartObjectResponse, ErrorDocument

router = APIRouter(dependencies=[Depends(require_json_content_type)])
log = get_logger()

# Documents the error contract in the OpenAPI schema
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorDocument} for status in (400, 413, 415, 500, 503)
}


@router.post("/charts", status_code=201, responses=_ERROR_RESPONSES)
async def create_chart(
    payload: ChartRenderRequest,
    exporter: Annotated[ChartExporter, Depends(get_chart_exporter)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChartObjectResponse:
    """Render the chart config to a PNG, store it privately, and return its metadata."""
    chart = await exporter.export(chart_config=payload.chart_config, language=payload.language)
    # Never log chart_config: charts may contain sensitive/pre-release data
    log.info("chart exported", chart_id=str(chart.id), key=chart.key, size_bytes=chart.size_bytes)
    return ChartObjectResponse(
        id=chart.id,
        created_at=chart.created_at,
        bucket=settings.s3_bucket,
        key=chart.key,
        content_type="image/png",
        size_bytes=chart.size_bytes,
        width=chart.width,
        height=chart.height,
    )
