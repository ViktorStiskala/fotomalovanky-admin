"""Health check endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health", operation_id="healthCheck")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}
