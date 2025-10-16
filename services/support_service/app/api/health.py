from fastapi import APIRouter, status

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", status_code=status.HTTP_200_OK)
async def healthcheck() -> dict[str, str]:
    """Return a simple health status payload."""

    return {"status": "ok"}
