"""Auth API — login, me, admin user management, training complete."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.audit.enforcement import complete_training, decode_training_token
from app.auth.deps import AdminUser, CurrentUser, get_current_user
from app.auth.jwt import ROLES, create_access_token
from app.auth.users import authenticate, create_user, list_users, public_user, set_user_password
from app.config import get_settings
from app.models.schemas import CreateUserRequest, LoginRequest, TokenResponse, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])
_optional_bearer = HTTPBearer(auto_error=False)


class TrainingCompleteRequest(BaseModel):
    token: Optional[str] = Field(None, description="Signed training link token")


class ResetPasswordRequest(BaseModel):
    password: Optional[str] = Field(
        None,
        min_length=8,
        description="New password; omit to auto-generate a temporary password",
    )


class ResetPasswordResponse(BaseModel):
    email: str
    temp_password: str
    user: UserPublic


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


@router.post("/training/complete")
def training_complete(
    req: TrainingCompleteRequest,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)] = None,
) -> Dict[str, Any]:
    """Self-service training completion via signed token or authenticated session."""
    email: Optional[str] = None
    if req.token:
        try:
            email = decode_training_token(req.token)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif creds and creds.credentials:
        try:
            user = get_current_user(creds)
            email = str(user.get("email") or "").lower()
        except HTTPException:
            raise
    if not email:
        raise HTTPException(
            status_code=400,
            detail="Provide a training token or authenticate to complete training",
        )
    row = complete_training(email)
    return {"status": "ok", "user_email": email, "training": row}


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


@router.post("/users/{email}/reset-password", response_model=ResetPasswordResponse)
def admin_reset_password(
    email: str, req: ResetPasswordRequest, _admin: AdminUser
) -> ResetPasswordResponse:
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits + "!@#$"
    new_password = req.password or "".join(secrets.choice(alphabet) for _ in range(14))
    try:
        user = set_user_password(email, new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return ResetPasswordResponse(
        email=str(user.get("email") or email).lower(),
        temp_password=new_password,
        user=UserPublic(**public_user(user)),
    )
