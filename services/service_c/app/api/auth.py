# services/service_c/app/api/auth.py
"""Authentication API — Register, Login, Profile, API Keys"""

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from shared.config.database import get_db
from shared.models.orm import Owner
from app.services.auth_service import (
    hash_password, verify_password, create_access_token,
    decode_access_token, generate_api_key, TokenPayload
)

router = APIRouter()
logger = logging.getLogger("service-c.auth")


# ── Models ──

class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=6, max_length=128)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

class ProfileResponse(BaseModel):
    id: str
    email: str
    name: str
    plan: str
    type: str
    api_key: Optional[str] = None
    created_at: str


# ── JWT Dependency ──

async def get_current_user(
    authorization: str = Header(..., description="Bearer <token>"),
    db: AsyncSession = Depends(get_db)
) -> Owner:
    """Extract and validate JWT from Authorization header"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization.split(" ", 1)[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    result = await db.execute(select(Owner).where(Owner.id == payload.sub))
    owner = result.scalar_one_or_none()
    if not owner or not owner.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    return owner


# ── Endpoints ──

@router.post("/register", response_model=AuthResponse)
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user"""
    # Check if email exists
    existing = await db.execute(select(Owner).where(Owner.email == request.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    owner = Owner(
        email=request.email,
        name=request.name,
        password_hash=hash_password(request.password),
    )
    db.add(owner)
    await db.commit()
    await db.refresh(owner)

    token = create_access_token(
        owner_id=str(owner.id),
        email=owner.email,
        name=owner.name,
        plan=owner.plan,
        type_=owner.type,
    )

    logger.info(f"New user registered: {owner.email}")

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(owner.id),
            "email": owner.email,
            "name": owner.name,
            "plan": owner.plan,
        }
    }


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login with email/password"""
    result = await db.execute(select(Owner).where(Owner.email == request.email))
    owner = result.scalar_one_or_none()

    if not owner or not verify_password(request.password, owner.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not owner.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    token = create_access_token(
        owner_id=str(owner.id),
        email=owner.email,
        name=owner.name,
        plan=owner.plan,
        type_=owner.type,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(owner.id),
            "email": owner.email,
            "name": owner.name,
            "plan": owner.plan,
        }
    }


@router.get("/me", response_model=ProfileResponse)
async def get_profile(current_user: Owner = Depends(get_current_user)):
    """Get current user profile"""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "name": current_user.name,
        "plan": current_user.plan,
        "type": current_user.type,
        "api_key": current_user.api_key,
        "created_at": current_user.created_at.isoformat(),
    }


@router.post("/generate-api-key")
async def generate_user_api_key(
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate or regenerate API key for external access (agentic systems)"""
    api_key = generate_api_key()
    current_user.api_key = api_key
    await db.commit()

    logger.info(f"API key generated for user: {current_user.email}")

    return {
        "api_key": api_key,
        "message": "Save this key securely. It won't be shown again in full."
    }
