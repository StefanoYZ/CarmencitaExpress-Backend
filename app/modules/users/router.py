from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.modules.users.schema import (
    PermissionCreate,
    PermissionResponse,
    PermissionUpdate,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.modules.users.service import (
    assign_permission_to_role,
    assign_role_to_user,
    create_permission,
    create_role,
    create_user,
    disable_role,
    get_permission,
    get_role,
    get_role_permissions,
    get_user,
    get_user_roles,
    list_permissions,
    list_roles,
    list_users,
    remove_permission_from_role,
    remove_role_from_user,
    update_permission,
    update_role,
    update_user,
)


users_router = APIRouter(prefix="/users", tags=["Users"])
roles_router = APIRouter(prefix="/roles", tags=["Roles"])
permissions_router = APIRouter(prefix="/permissions", tags=["Permissions"])


@users_router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user_endpoint(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("users.write")),
) -> UserResponse:
    try:
        return create_user(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@users_router.get("", response_model=list[UserResponse])
def list_users_endpoint(
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("users.read")),
) -> list[UserResponse]:
    return list_users(db)


@users_router.get("/{user_id}", response_model=UserResponse)
def get_user_endpoint(
    user_id: int,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("users.read")),
) -> UserResponse:
    user = get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@users_router.put("/{user_id}", response_model=UserResponse)
def update_user_endpoint(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("users.update")),
) -> UserResponse:
    try:
        user = update_user(db, user_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@users_router.post("/{user_id}/roles/{role_id}", response_model=UserResponse)
def assign_role_to_user_endpoint(
    user_id: int,
    role_id: int,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("users.update")),
) -> UserResponse:
    try:
        user = assign_role_to_user(db, user_id, role_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@users_router.delete("/{user_id}/roles/{role_id}", response_model=UserResponse)
def remove_role_from_user_endpoint(
    user_id: int,
    role_id: int,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("users.update")),
) -> UserResponse:
    try:
        user = remove_role_from_user(db, user_id, role_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@users_router.get("/{user_id}/roles", response_model=list[RoleResponse])
def get_user_roles_endpoint(
    user_id: int,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("users.read")),
) -> list[RoleResponse]:
    roles = get_user_roles(db, user_id)
    if roles is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return roles


@roles_router.post("", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
def create_role_endpoint(
    payload: RoleCreate,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("roles.write")),
) -> RoleResponse:
    try:
        return create_role(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@roles_router.get("", response_model=list[RoleResponse])
def list_roles_endpoint(
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("roles.read")),
) -> list[RoleResponse]:
    return list_roles(db)


@roles_router.get("/{role_id}", response_model=RoleResponse)
def get_role_endpoint(
    role_id: int,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("roles.read")),
) -> RoleResponse:
    role = get_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return role


@roles_router.put("/{role_id}", response_model=RoleResponse)
def update_role_endpoint(
    role_id: int,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("roles.update")),
) -> RoleResponse:
    try:
        role = update_role(db, role_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return role


@roles_router.delete("/{role_id}", response_model=RoleResponse)
def disable_role_endpoint(
    role_id: int,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("roles.update")),
) -> RoleResponse:
    role = disable_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return role


@roles_router.post("/{role_id}/permissions/{permission_id}", response_model=RoleResponse)
def assign_permission_to_role_endpoint(
    role_id: int,
    permission_id: int,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("roles.assign_permissions")),
) -> RoleResponse:
    try:
        role = assign_permission_to_role(db, role_id, permission_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return role


@roles_router.delete("/{role_id}/permissions/{permission_id}", response_model=RoleResponse)
def remove_permission_from_role_endpoint(
    role_id: int,
    permission_id: int,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("roles.assign_permissions")),
) -> RoleResponse:
    try:
        role = remove_permission_from_role(db, role_id, permission_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return role


@roles_router.get("/{role_id}/permissions", response_model=list[PermissionResponse])
def get_role_permissions_endpoint(
    role_id: int,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("roles.read")),
) -> list[PermissionResponse]:
    permissions = get_role_permissions(db, role_id)
    if permissions is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return permissions


@permissions_router.get("", response_model=list[PermissionResponse])
def list_permissions_endpoint(
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("permissions.read")),
) -> list[PermissionResponse]:
    return list_permissions(db)


@permissions_router.get("/{permission_id}", response_model=PermissionResponse)
def get_permission_endpoint(
    permission_id: int,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("permissions.read")),
) -> PermissionResponse:
    permission = get_permission(db, permission_id)
    if permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")
    return permission


@permissions_router.post("", response_model=PermissionResponse, status_code=status.HTTP_201_CREATED)
def create_permission_endpoint(
    payload: PermissionCreate,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("permissions.write")),
) -> PermissionResponse:
    try:
        return create_permission(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@permissions_router.put("/{permission_id}", response_model=PermissionResponse)
def update_permission_endpoint(
    permission_id: int,
    payload: PermissionUpdate,
    db: Session = Depends(get_db),
    _current_user=Depends(require_permission("permissions.write")),
) -> PermissionResponse:
    try:
        permission = update_permission(db, permission_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")
    return permission
    set_user_active,
