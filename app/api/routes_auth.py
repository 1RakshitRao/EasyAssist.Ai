"""Auth API — login, me, admin user management."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, status

from app.auth.deps import AdminUser, CurrentUser
from app.auth.jwt import ROLES, create_access_token
from app.auth.users import authenticate, create_user, list_users, public_user
from app.config import get_settings
from app.models.schemas import CreateUserRequest, LoginRequest, TokenResponse, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest) -> TokenResponse:
    user = authenticate(req.email, req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    settings = get_settings()
    token = create_access_token(
        user_id=str(user["id"]),
        email=str(user["email"]),
        role=str(user["role"]),
        name=str(user.get("name") or ""),
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_expire_minutes * 60,
        user=UserPublic(**public_user(user)),
    )


@router.get("/me", response_model=UserPublic)
def me(user: CurrentUser) -> UserPublic:
    return UserPublic(**user)


@router.get("/users", response_model=List[UserPublic])
def admin_list_users(_admin: AdminUser) -> List[UserPublic]:
    return [UserPublic(**public_user(u)) for u in list_users()]


@router.post("/users", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def admin_create_user(req: CreateUserRequest, _admin: AdminUser) -> UserPublic:
    role = req.role.lower().strip()
    if role not in ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"role must be one of: {', '.join(ROLES)}",
        )
    try:
        user = create_user(
            email=req.email,
            password=req.password,
            role=role,
            name=req.name or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserPublic(**public_user(user))
