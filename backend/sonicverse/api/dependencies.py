"""API dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sonicverse.core.auth import AuthUser
from sonicverse.core.database import get_db
from sonicverse.schemas.common import PaginationParams


async def get_pagination(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
) -> PaginationParams:
    """Get pagination parameters."""
    return PaginationParams(page=page, page_size=page_size)


def get_current_user(request: Request) -> AuthUser:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def require_admin(user: AuthUser) -> AuthUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="没有权限")
    return user


# Type aliases for dependency injection
DbSession = Annotated[AsyncSession, Depends(get_db)]
Pagination = Annotated[PaginationParams, Depends(get_pagination)]
CurrentUser = Annotated[AuthUser, Depends(get_current_user)]
