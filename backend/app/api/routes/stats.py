"""Dashboard statistics API."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DBSession
from app.services.stats_service import StatsService

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats")
async def get_stats(
    current_user: CurrentUser,
    db: DBSession,
) -> dict:
    """Aggregate dashboard stats for the current user's accessible KBs."""
    service = StatsService(db)
    stats = await service.get_user_stats(current_user.id)
    return {"data": stats}
