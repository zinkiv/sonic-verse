"""Auth and user-management routes (navi-dock style)."""

from fastapi import APIRouter, HTTPException, Request

from sonicverse.api.auth_service import (
    admin_set_password,
    auth_status,
    change_password,
    create_user,
    delete_user,
    list_users,
    login,
    set_disabled,
    user_from_token,
)
from sonicverse.api.dependencies import CurrentUser, DbSession, require_admin
from sonicverse.api.middleware import extract_token
from sonicverse.core.auth import AuthError
from sonicverse.schemas.auth import (
    AdminSetPasswordRequest,
    AuthStatus,
    ChangePasswordRequest,
    CreateUserRequest,
    LoginRequest,
    LoginResult,
    PatchUserRequest,
    UserListResponse,
    UserPublic,
)

router = APIRouter(tags=["auth"])


def _raise(exc: AuthError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/auth/status", response_model=AuthStatus)
async def get_auth_status(db: DbSession, request: Request) -> AuthStatus:
    status = await auth_status(db, extract_token(request))
    return AuthStatus.model_validate(status)


@router.post("/auth/login", response_model=LoginResult)
async def auth_login(db: DbSession, body: LoginRequest) -> LoginResult:
    try:
        result = await login(db, body.username, body.password)
    except AuthError as exc:
        _raise(exc)
    await db.commit()
    return LoginResult.model_validate(result)


@router.put("/auth/password")
async def auth_change_password(
    db: DbSession,
    body: ChangePasswordRequest,
    user: CurrentUser,
) -> dict:
    try:
        await change_password(db, user.id, body.old_password, body.new_password)
    except AuthError as exc:
        _raise(exc)
    await db.commit()
    return {"ok": True}


@router.get("/users", response_model=UserListResponse)
async def get_users(db: DbSession, user: CurrentUser) -> UserListResponse:
    require_admin(user)
    return UserListResponse(users=await list_users(db))


@router.post("/users", response_model=UserPublic, status_code=201)
async def post_user(db: DbSession, body: CreateUserRequest, request: Request) -> UserPublic:
    actor = getattr(request.state, "user", None)
    if actor is None:
        actor = await user_from_token(db, extract_token(request))
    try:
        created = await create_user(
            db,
            username=body.username,
            password=body.password,
            role=body.role,
            actor=actor,
        )
    except AuthError as exc:
        _raise(exc)
    await db.commit()
    return created


@router.patch("/users/{user_id}", response_model=UserPublic)
async def patch_user(
    db: DbSession,
    user_id: str,
    body: PatchUserRequest,
    user: CurrentUser,
) -> UserPublic:
    require_admin(user)
    if body.disabled is None:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    try:
        updated = await set_disabled(db, user, user_id, body.disabled)
    except AuthError as exc:
        _raise(exc)
    await db.commit()
    return updated


@router.put("/users/{user_id}/password")
async def put_user_password(
    db: DbSession,
    user_id: str,
    body: AdminSetPasswordRequest,
    user: CurrentUser,
) -> dict:
    require_admin(user)
    try:
        await admin_set_password(db, user_id, body.new_password)
    except AuthError as exc:
        _raise(exc)
    await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
async def remove_user(db: DbSession, user_id: str, user: CurrentUser) -> dict:
    require_admin(user)
    try:
        await delete_user(db, user, user_id)
    except AuthError as exc:
        _raise(exc)
    await db.commit()
    return {"ok": True}
