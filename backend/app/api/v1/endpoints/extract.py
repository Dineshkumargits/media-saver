from fastapi import APIRouter, HTTPException, Request

from app.core.limiter import limiter
from app.core.config import get_settings
from app.models.schemas import ExtractRequest, ExtractResponse
from app.services.extractor import ExtractionError, extract_metadata

router = APIRouter()
settings = get_settings()


@router.post("/extract", response_model=ExtractResponse)
@limiter.limit(settings.RATE_LIMIT_EXTRACT)
async def extract(request: Request, payload: ExtractRequest) -> ExtractResponse:
    """Resolves available download formats for a given media URL without
    downloading anything to disk."""
    try:
        return await extract_metadata(str(payload.url))
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
