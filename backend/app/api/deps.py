"""FastAPI auth dependencies: JWT parsing, user loading, role guards."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token
from app.models import Role, User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None:
        raise Unauthorized("Missing bearer token")
    claims = decode_token(credentials.credentials, expected_type="access")
    user = db.get(User, claims["sub"])
    if user is None or not user.is_active:
        raise Unauthorized("User inactive or deleted")
    return user


def get_current_user_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User | None:
    if credentials is None:
        return None
    claims = decode_token(credentials.credentials, expected_type="access")
    user = db.get(User, claims["sub"])
    return user if user and user.is_active else None


def require_roles(*roles: Role):
    """Dependency factory: allow only listed roles."""

    def guard(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise Forbidden(f"Requires role: {', '.join(r.value for r in roles)}")
        return user

    return guard


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]
AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]
EngineerUser = Annotated[User, Depends(require_roles(Role.ADMIN, Role.ENGINEER))]
