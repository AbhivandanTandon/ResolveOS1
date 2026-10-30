"""Mock authentication (pick a seeded user) with real server-side role enforcement."""

from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, utcnow
from .models import User


def issue_token(user: User) -> str:
    exp = utcnow() + timedelta(minutes=settings.token_ttl_minutes)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, settings.jwt_secret, algorithm="HS256")


def _decode(token: str) -> int:
    try:
        return int(jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, detail={"code": "INVALID_TOKEN", "message": "Sign in again."})


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, detail={"code": "NOT_AUTHENTICATED", "message": "Sign in to continue."})
    user = db.get(User, _decode(header[7:]))
    if user is None or not user.active:
        raise HTTPException(401, detail={"code": "INVALID_USER", "message": "Unknown or inactive user."})
    return user  # role is always read from the database, never trusted from the token


def require_roles(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, detail={"code": "FORBIDDEN_ROLE",
                                             "message": f"This needs one of: {', '.join(roles)}."})
        return user

    return dep
