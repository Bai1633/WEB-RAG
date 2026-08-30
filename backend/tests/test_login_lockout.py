"""Tests for login lockout (brute-force protection, Redis fail-open)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.utils.exceptions import AppException
from app.utils.login_lockout import LoginLockout


def _redis_mock(get_return=None, incr_return=1):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=get_return)
    redis.incr = AsyncMock(return_value=incr_return)
    redis.expire = AsyncMock()
    redis.delete = AsyncMock()
    return redis


class TestLoginLockout:
    @pytest.mark.asyncio
    async def test_locked_at_threshold(self):
        lockout = LoginLockout(max_attempts=5, window_seconds=900)
        with patch("app.utils.login_lockout.get_redis", return_value=_redis_mock(get_return="5")):
            assert await lockout.is_locked("a@b.com") is True

    @pytest.mark.asyncio
    async def test_not_locked_below_threshold(self):
        lockout = LoginLockout(max_attempts=5, window_seconds=900)
        with patch("app.utils.login_lockout.get_redis", return_value=_redis_mock(get_return="2")):
            assert await lockout.is_locked("a@b.com") is False

    @pytest.mark.asyncio
    async def test_fail_open_when_redis_down(self):
        lockout = LoginLockout(max_attempts=5, window_seconds=900)
        redis = _redis_mock()
        redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
        redis.incr = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch("app.utils.login_lockout.get_redis", return_value=redis):
            assert await lockout.is_locked("a@b.com") is False
            assert await lockout.record_failure("a@b.com") == 0

    @pytest.mark.asyncio
    async def test_record_failure_sets_expiry_once(self):
        lockout = LoginLockout(max_attempts=5, window_seconds=900)
        redis = _redis_mock(incr_return=1)
        with patch("app.utils.login_lockout.get_redis", return_value=redis):
            count = await lockout.record_failure("A@B.com")
        assert count == 1
        redis.incr.assert_awaited_once_with("login_fail:a@b.com")
        redis.expire.assert_awaited_once_with("login_fail:a@b.com", 900)

    @pytest.mark.asyncio
    async def test_reset_deletes_key(self):
        lockout = LoginLockout(max_attempts=5, window_seconds=900)
        redis = _redis_mock()
        with patch("app.utils.login_lockout.get_redis", return_value=redis):
            await lockout.reset("a@b.com")
        redis.delete.assert_awaited_once_with("login_fail:a@b.com")


class TestAuthServiceLockoutIntegration:
    @pytest.mark.asyncio
    async def test_login_locked_raises_429(self):
        from unittest.mock import MagicMock

        from app.services.auth_service import AuthService

        service = AuthService(AsyncMock())
        service.user_repo = MagicMock()
        service.user_repo.get_by_email = AsyncMock(return_value=MagicMock(is_active=True))

        with patch(
            "app.services.auth_service.login_lockout"
        ) as lockout:
            lockout.is_locked = AsyncMock(return_value=True)
            with pytest.raises(AppException) as exc_info:
                await service.login("a@b.com", "wrong-password")

        assert exc_info.value.status_code == 429
        assert exc_info.value.code == "login_locked"
        lockout.record_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_password_records_failure(self):
        from unittest.mock import MagicMock

        from app.services import auth_service as auth_module
        from app.services.auth_service import AuthService

        service = AuthService(AsyncMock())
        user = MagicMock(is_active=True)
        user.hashed_password = "argon2hash"
        service.user_repo = MagicMock()
        service.user_repo.get_by_email = AsyncMock(return_value=user)

        with (
            patch(f"{auth_module.__name__}.login_lockout") as lockout,
            patch(f"{auth_module.__name__}.verify_password", return_value=False),
        ):
            lockout.is_locked = AsyncMock(return_value=False)
            lockout.record_failure = AsyncMock(return_value=1)

            with pytest.raises(ValueError):
                await service.login("a@b.com", "wrong")

            lockout.record_failure.assert_awaited_once_with("a@b.com")
            lockout.reset.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_login_resets_counter(self):
        from unittest.mock import MagicMock

        from app.services import auth_service as auth_module
        from app.services.auth_service import AuthService

        service = AuthService(AsyncMock())
        user = MagicMock(is_active=True, id="u-1")
        user.hashed_password = "argon2hash"
        service.user_repo = MagicMock()
        service.user_repo.get_by_email = AsyncMock(return_value=user)

        with (
            patch(f"{auth_module.__name__}.login_lockout") as lockout,
            patch(f"{auth_module.__name__}.verify_password", return_value=True),
            patch(f"{auth_module.__name__}.create_access_token", return_value="at"),
            patch(f"{auth_module.__name__}.create_refresh_token", return_value="rt"),
        ):
            lockout.is_locked = AsyncMock(return_value=False)
            lockout.reset = AsyncMock()

            await service.login("a@b.com", "correct")

            lockout.reset.assert_awaited_once_with("a@b.com")
