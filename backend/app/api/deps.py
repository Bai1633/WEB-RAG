"""FastAPI dependency injection utilities."""

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import decode_token
from app.db.database import get_db
from app.db.models import User
from app.db.repositories.user_repo import UserRepository
from app.utils.rate_limit import chat_rate_limiter, upload_rate_limiter

settings = get_settings()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Get current authenticated user from JWT token."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(user_id_str)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DBSession = Annotated[AsyncSession, Depends(get_db)]


# ===== Per-user rate limits for expensive endpoints =====
# The global IP-based limiter (middleware) stays as a coarse outer layer; these
# bucket per user so a shared office IP cannot exhaust one user's quota, and
# heavy endpoints get budgets that match their cost (LLM calls, embeddings).

async def enforce_chat_rate_limit(current_user: CurrentUser) -> None:
    """Dependency: per-user token bucket for chat (LLM) requests."""
    allowed = await chat_rate_limiter.allow(f"user:{current_user.id}")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many chat requests. Please slow down.",
            headers={"Retry-After": "10"},
        )


async def enforce_upload_rate_limit(current_user: CurrentUser) -> None:
    """Dependency: per-user token bucket for document uploads."""
    allowed = await upload_rate_limiter.allow(f"user:{current_user.id}")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many uploads. Please try again shortly.",
            headers={"Retry-After": "60"},
        )


ChatRateLimit = Annotated[None, Depends(enforce_chat_rate_limit)]
UploadRateLimit = Annotated[None, Depends(enforce_upload_rate_limit)]


# ===== Knowledge-base RBAC permission dependencies =====
# Centralized so all route modules share a single implementation.

if TYPE_CHECKING:
    from app.services.kb_service import KBService


def _get_kb_service(db: AsyncSession) -> "KBService":
    from app.services.kb_service import KBService

    return KBService(db)


async def require_kb_viewer(
    kb_id: str,
    current_user: CurrentUser,
    db: DBSession,
) -> None:
    """Dependency: require viewer role or higher on the knowledge base."""
    from uuid import UUID

    from app.db.models import KBRole

    service = _get_kb_service(db)
    has_access = await service.check_permission(UUID(kb_id), current_user.id, KBRole.VIEWER)
    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this knowledge base",
        )


async def require_kb_editor(
    kb_id: str,
    current_user: CurrentUser,
    db: DBSession,
) -> None:
    """Dependency: require editor role or higher on the knowledge base."""
    from uuid import UUID

    from app.db.models import KBRole

    service = _get_kb_service(db)
    has_access = await service.check_permission(UUID(kb_id), current_user.id, KBRole.EDITOR)
    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have editor permission for this knowledge base",
        )


async def require_kb_owner(
    kb_id: str,
    current_user: CurrentUser,
    db: DBSession,
) -> None:
    """Dependency: require owner role on the knowledge base."""
    from uuid import UUID

    from app.db.models import KBRole

    service = _get_kb_service(db)
    has_access = await service.check_permission(UUID(kb_id), current_user.id, KBRole.OWNER)
    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have owner permission for this knowledge base",
        )
