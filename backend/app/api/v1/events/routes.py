"""Events API routes - exposes event schema for frontend type generation."""

from fastapi import APIRouter

from app.services.mercure.events import MercureEventUnion

router = APIRouter(tags=["events"])


@router.get(
    "/events/schema",
    response_model=MercureEventUnion,
    operation_id="getMercureEventSchema",
    include_in_schema=True,
    summary="Mercure event schema (for documentation only)",
    description="This endpoint documents the shape of Mercure SSE events. "
    "Do not call this endpoint directly - subscribe to Mercure instead.",
)
async def get_event_schema() -> None:
    """This endpoint exists only to expose event types in OpenAPI schema."""
    raise NotImplementedError("This endpoint is for schema documentation only")
