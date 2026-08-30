"""Authentication service - business logic for auth."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_refresh_token_hash,
    hash_password,
    verify_password,
)
from app.db.models import RefreshToken, User
from app.db.repositories.user_repo import UserRepository
from app.utils.exceptions import AppException
from app.utils.login_lockout import login_lockout

settings = get_settings()


class AuthService:
    """Authentication service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_repo = UserRepository(db)

    async def register(self, email: str, password: str) -> User:
        """Register a new user."""
        existing = await self.user_repo.get_by_email(email)
        if existing:
            raise ValueError("User with this email already exists")

        hashed = hash_password(password)
        user = await self.user_repo.create(email=email, hashed_password=hashed)
        return user

    async def login(self, email: str, password: str) -> tuple[str, str, int]:
        """Authenticate user and return (access_token, refresh_token, expires_in)."""
        user = await self.user_repo.get_by_email(email)
        if not user or not user.is_active:
            raise ValueError("Invalid email or password")

        # Brute-force protection: lock the account after too many failures.
        # AppException(429) bypasses this route's ValueError->401 mapping and is
        # rendered by the global exception handler.
        if await login_lockout.is_locked(email):
            raise AppException(
                message="登录失败次数过多，账号已临时锁定，请稍后再试",
                status_code=429,
                code="login_locked",
            )

        if not verify_password(password, user.hashed_password):
            await login_lockout.record_failure(email)
            raise ValueError("Invalid email or password")

        await login_lockout.reset(email)

        access_token = create_access_token(subject=user.id)
        refresh_token = create_refresh_token(subject=user.id)

        # Store refresh token hash
        token_hash = get_refresh_token_hash(refresh_token)
        expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
        rt = RefreshToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at)
        self.db.add(rt)
        await self.db.flush()

        expires_in = settings.access_token_expire_minutes * 60
        return access_token, refresh_token, expires_in

    async def refresh(self, refresh_token: str) -> tuple[str, str, int]:
        """Refresh access token using refresh token.

        Returns (new_access_token, new_refresh_token, expires_in).
        Implements token rotation: old refresh token is revoked.
        """
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise ValueError("Invalid refresh token")

        user_id_str = payload.get("sub")
        if not user_id_str:
            raise ValueError("Invalid refresh token")

        # Check if refresh token exists and is not expired
        token_hash = get_refresh_token_hash(refresh_token)
        result = await self.db.execute(
            select(RefreshToken.expires_at).where(RefreshToken.token_hash == token_hash)
        )
        rt_expires = result.scalar_one_or_none()
        if rt_expires is None:
            raise ValueError("Refresh token not found or revoked")

        if rt_expires.replace(tzinfo=UTC) < datetime.now(UTC):
            # Clean up expired token
            await self.db.execute(
                delete(RefreshToken).where(RefreshToken.token_hash == token_hash)
            )
            await self.db.flush()
            raise ValueError("Refresh token expired")

        user_id = UUID(user_id_str)
        user = await self.user_repo.get_by_id(user_id)
        if not user or not user.is_active:
            raise ValueError("User not found or inactive")

        # Revoke old refresh token
        await self.db.execute(
            delete(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )

        # Issue new tokens (rotation)
        new_access_token = create_access_token(subject=user.id)
        new_refresh_token = create_refresh_token(subject=user.id)

        new_token_hash = get_refresh_token_hash(new_refresh_token)
        new_expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
        new_rt = RefreshToken(
            user_id=user.id, token_hash=new_token_hash, expires_at=new_expires_at
        )
        self.db.add(new_rt)
        await self.db.flush()

        expires_in = settings.access_token_expire_minutes * 60
        return new_access_token, new_refresh_token, expires_in

    async def logout(self, user_id: UUID, refresh_token: str | None = None) -> None:
        """Logout user: revoke refresh token(s).

        If refresh_token is provided, revoke only that token.
        Otherwise revoke all tokens for the user.
        """
        if refresh_token:
            token_hash = get_refresh_token_hash(refresh_token)
            await self.db.execute(
                delete(RefreshToken).where(RefreshToken.token_hash == token_hash)
            )
        else:
            await self.db.execute(
                delete(RefreshToken).where(RefreshToken.user_id == user_id)
            )
        await self.db.flush()

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        """Get user by ID."""
        return await self.user_repo.get_by_id(user_id)
