from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.modules.auth.schema import LoginRequest, TokenResponse
from app.modules.users.service import authenticate_user, build_user_response


def login_internal_user(db: Session, payload: LoginRequest) -> TokenResponse | None:
    user = authenticate_user(db, payload.username, payload.password)
    if user is None:
        return None
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
