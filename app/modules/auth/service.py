from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.modules.auth.schema import LoginRequest, TokenResponse
from app.modules.users.service import authenticate_user, build_user_response
from app.modules.agencies.model import Agency


def login_internal_user(db: Session, payload: LoginRequest) -> TokenResponse | None:
    user = authenticate_user(db, payload.username, payload.password)
    if user is None:
        return None
    business_roles = {role.name for role in user.roles if role.is_active} & {"AGENCY_ADMIN", "SECRETARIA", "ESTIBA"}
    if business_roles and (user.agency_id is None or db.get(Agency, user.agency_id) is None):
        raise ValueError("Tu cuenta necesita una agencia asignada. Contacta al administrador general.")
    if business_roles & {"SECRETARIA", "ESTIBA"} and not db.query(Agency.id).filter(
        Agency.id == user.agency_id, Agency.is_active.is_(True)
    ).first():
        raise ValueError("La agencia asignada está inactiva.")
    user_response = build_user_response(user)
    token = create_access_token(
        {
            "sub": str(user.id),
            "username": user.username,
            "roles": user_response.roles,
            "permissions": user_response.permissions,
        }
    )
    return TokenResponse(access_token=token, token_type="bearer", user=user_response)
