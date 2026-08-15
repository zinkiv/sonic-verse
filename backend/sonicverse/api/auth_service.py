"""Account operations: bootstrap admin, login, user admin."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonicverse.core.auth import (
    AuthError,
    AuthUser,
    hash_password,
    issue_token,
    parse_token,
    verify_password,
)
from sonicverse.models.user import User
from sonicverse.schemas.auth import UserPublic

MIN_USERNAME = 2
MAX_USERNAME = 32
MIN_PASSWORD = 6


def _public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        username=user.username,
        role=user.role,
        disabled=bool(user.disabled),
        created_at=user.created_at,
    )


def _auth_user(user: User) -> AuthUser:
    return AuthUser(
        id=user.id,
        username=user.username,
        role=user.role,
        disabled=bool(user.disabled),
    )


def validate_credentials(username: str, password: str) -> tuple[str, str]:
    name = (username or "").strip()
    if not name:
        raise AuthError("用户名不能为空")
    n = len(name)
    if n < MIN_USERNAME:
        raise AuthError("用户名至少 2 个字符")
    if n > MAX_USERNAME:
        raise AuthError("用户名最多 32 个字符")
    if not password:
        raise AuthError("密码不能为空")
    if len(password) < MIN_PASSWORD:
        raise AuthError("密码至少 6 位")
    return name, password


async def user_count(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count(User.id))) or 0)


async def admin_count(session: AsyncSession, *, exclude_id: str | None = None) -> int:
    query = select(func.count(User.id)).where(User.role == "admin", User.disabled.is_(False))
    if exclude_id:
        query = query.where(User.id != exclude_id)
    return int(await session.scalar(query) or 0)


async def find_by_id(session: AsyncSession, user_id: str) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def find_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def auth_status(session: AsyncSession, token: str | None) -> dict:
    setup_required = await user_count(session) == 0
    user = None
    if token:
        current = await user_from_token(session, token)
        if current is not None:
            loaded = await find_by_id(session, current.id)
            if loaded is not None:
                user = _public(loaded)
    return {"setup_required": setup_required, "user": user}


async def user_from_token(session: AsyncSession, token: str | None) -> AuthUser | None:
    if not token:
        return None
    claims = parse_token(token)
    if not claims:
        return None
    user = await find_by_id(session, str(claims["uid"]))
    if user is None or user.disabled:
        return None
    return _auth_user(user)


async def login(session: AsyncSession, username: str, password: str) -> dict:
    name = (username or "").strip()
    if not name or not password:
        raise AuthError("用户名或密码错误", status_code=401)
    user = await find_by_username(session, name)
    if user is None or user.disabled or not verify_password(password, user.password_hash):
        raise AuthError("用户名或密码错误", status_code=401)
    token = issue_token(_auth_user(user))
    return {"token": token, "user": _public(user)}


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    role: str,
    actor: AuthUser | None,
) -> UserPublic:
    name, pwd = validate_credentials(username, password)
    count = await user_count(session)
    chosen = (role or "user").strip()
    if chosen not in {"admin", "user"}:
        chosen = "user"

    if count == 0:
        chosen = "admin"
    elif actor is None or not actor.is_admin:
        raise AuthError("没有权限", status_code=403)

    existing = await find_by_username(session, name)
    if existing is not None:
        raise AuthError("用户名已存在")

    user = User(
        username=name,
        password_hash=hash_password(pwd),
        role=chosen,
        disabled=False,
    )
    session.add(user)
    await session.flush()
    return _public(user)


async def list_users(session: AsyncSession) -> list[UserPublic]:
    result = await session.execute(select(User).order_by(User.created_at.asc()))
    return [_public(row) for row in result.scalars().all()]


async def change_password(session: AsyncSession, user_id: str, old_password: str, new_password: str) -> None:
    if not new_password:
        raise AuthError("密码不能为空")
    if len(new_password) < MIN_PASSWORD:
        raise AuthError("密码至少 6 位")
    user = await find_by_id(session, user_id)
    if user is None:
        raise AuthError("用户不存在", status_code=404)
    if not verify_password(old_password, user.password_hash):
        raise AuthError("当前密码不正确")
    user.password_hash = hash_password(new_password)


async def admin_set_password(session: AsyncSession, user_id: str, new_password: str) -> None:
    if not new_password:
        raise AuthError("密码不能为空")
    if len(new_password) < MIN_PASSWORD:
        raise AuthError("密码至少 6 位")
    user = await find_by_id(session, user_id)
    if user is None:
        raise AuthError("用户不存在", status_code=404)
    user.password_hash = hash_password(new_password)


async def set_disabled(session: AsyncSession, actor: AuthUser, user_id: str, disabled: bool) -> UserPublic:
    user = await find_by_id(session, user_id)
    if user is None:
        raise AuthError("用户不存在", status_code=404)
    if disabled and user.role == "admin" and await admin_count(session, exclude_id=user.id) < 1:
        raise AuthError("不能禁用最后一个管理员")
    user.disabled = disabled
    await session.flush()
    return _public(user)


async def delete_user(session: AsyncSession, actor: AuthUser, user_id: str) -> None:
    user = await find_by_id(session, user_id)
    if user is None:
        raise AuthError("用户不存在", status_code=404)
    if user.role == "admin" and await admin_count(session, exclude_id=user.id) < 1:
        raise AuthError("不能删除最后一个管理员")
    await session.delete(user)
