import secrets
from enum import StrEnum

from fastapi import Depends, Header, HTTPException, status

from app.config.settings import get_settings


class Role(StrEnum): VIEWER = "viewer"; OPERATOR = "operator"; ADMIN = "admin"


def require_role(required: Role):
    def check(x_api_key: str | None = Header(default=None)) -> Role:
        settings = get_settings()
        if not settings.auth_enabled and settings.environment == "development": return Role.ADMIN
        role = Role.VIEWER
        if settings.admin_api_key and x_api_key and secrets.compare_digest(x_api_key, settings.admin_api_key): role = Role.ADMIN
        elif settings.operator_api_key and x_api_key and secrets.compare_digest(x_api_key, settings.operator_api_key): role = Role.OPERATOR
        order = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}
        if order[role] < order[required]: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return role
    return check
