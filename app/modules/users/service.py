from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.modules.users import repository
from app.modules.users.defaults import BASE_PERMISSIONS, BASE_ROLE_DESCRIPTIONS, BASE_ROLE_PERMISSIONS
from app.modules.users.model import InternalUser, Permission, Role
from app.modules.users.schema import (
    AssignmentResponse,
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


def list_users(db: Session) -> list[UserResponse]:
    return [build_user_response(user) for user in repository.list_users(db)]


def get_user(db: Session, user_id: int) -> UserResponse | None:
    user = repository.get_user_by_id(db, user_id)
    if user is None:
        return None
    return build_user_response(user)


def create_user(db: Session, payload: UserCreate) -> UserResponse:
    _ensure_username_available(db, payload.username)
    user = repository.create_user(db, payload, hash_password(payload.password))
    return build_user_response(user)


def update_user(db: Session, user_id: int, payload: UserUpdate) -> UserResponse | None:
    user = repository.get_user_by_id(db, user_id)
    if user is None:
        return None
    if payload.username is not None and payload.username != user.username:
        _ensure_username_available(db, payload.username)
    password_hash = hash_password(payload.password) if payload.password else None
    updated_user = repository.update_user(db, user, payload, password_hash)
    return build_user_response(updated_user)


def set_user_active(db: Session, user_id: int, is_active: bool) -> UserResponse | None:
    user = repository.get_user_by_id(db, user_id)
    if user is None:
        return None
    updated_user = repository.set_user_active(db, user, is_active)
    return build_user_response(updated_user)


def list_roles(db: Session) -> list[RoleResponse]:
    return [build_role_response(role) for role in repository.list_roles(db)]


def get_role(db: Session, role_id: int) -> RoleResponse | None:
    role = repository.get_role_by_id(db, role_id)
    if role is None:
        return None
    return build_role_response(role)


def create_role(db: Session, payload: RoleCreate) -> RoleResponse:
    _ensure_role_name_available(db, payload.name)
    role = repository.create_role(db, payload)
    return build_role_response(role)


def update_role(db: Session, role_id: int, payload: RoleUpdate) -> RoleResponse | None:
    role = repository.get_role_by_id(db, role_id)
    if role is None:
        return None
    if payload.name is not None and payload.name != role.name:
        _ensure_role_name_available(db, payload.name)
    updated_role = repository.update_role(db, role, payload)
    return build_role_response(updated_role)


def disable_role(db: Session, role_id: int) -> RoleResponse | None:
    role = repository.get_role_by_id(db, role_id)
    if role is None:
        return None
    disabled_role = repository.disable_role(db, role)
    return build_role_response(disabled_role)


def list_permissions(db: Session) -> list[PermissionResponse]:
    return [PermissionResponse.model_validate(permission) for permission in repository.list_permissions(db)]


def get_permission(db: Session, permission_id: int) -> PermissionResponse | None:
    permission = repository.get_permission_by_id(db, permission_id)
    if permission is None:
        return None
    return PermissionResponse.model_validate(permission)


def create_permission(db: Session, payload: PermissionCreate) -> PermissionResponse:
    _ensure_permission_code_available(db, payload.code)
    permission = repository.create_permission(db, payload)
    return PermissionResponse.model_validate(permission)


def update_permission(db: Session, permission_id: int, payload: PermissionUpdate) -> PermissionResponse | None:
    permission = repository.get_permission_by_id(db, permission_id)
    if permission is None:
        return None
    if payload.code is not None and payload.code != permission.code:
        _ensure_permission_code_available(db, payload.code)
    updated_permission = repository.update_permission(db, permission, payload)
    return PermissionResponse.model_validate(updated_permission)


def assign_role_to_user(db: Session, user_id: int, role_id: int) -> UserResponse | None:
    user = repository.get_user_by_id(db, user_id)
    if user is None:
        return None
    role = repository.get_role_by_id(db, role_id)
    if role is None:
        raise LookupError("Role not found")
    if not role.is_active:
        raise ValueError("No se puede asignar un rol inactivo")
    if any(existing_role.id == role.id for existing_role in user.roles):
        raise ValueError("El usuario ya tiene asignado ese rol")
    updated_user = repository.assign_role_to_user(db, user, role)
    return build_user_response(updated_user)


def remove_role_from_user(db: Session, user_id: int, role_id: int) -> UserResponse | None:
    user = repository.get_user_by_id(db, user_id)
    if user is None:
        return None
    role = repository.get_role_by_id(db, role_id)
    if role is None:
        raise LookupError("Role not found")
    if not any(existing_role.id == role.id for existing_role in user.roles):
        raise ValueError("El usuario no tiene asignado ese rol")
    updated_user = repository.remove_role_from_user(db, user, role)
    return build_user_response(updated_user)


def get_user_roles(db: Session, user_id: int) -> list[RoleResponse] | None:
    user = repository.get_user_by_id(db, user_id)
    if user is None:
        return None
    return [build_role_response(role) for role in sorted(user.roles, key=lambda item: item.id)]


def assign_permission_to_role(db: Session, role_id: int, permission_id: int) -> RoleResponse | None:
    role = repository.get_role_by_id(db, role_id)
    if role is None:
        return None
    permission = repository.get_permission_by_id(db, permission_id)
    if permission is None:
        raise LookupError("Permission not found")
    if any(existing_permission.id == permission.id for existing_permission in role.permissions):
        raise ValueError("El rol ya tiene asignado ese permiso")
    updated_role = repository.assign_permission_to_role(db, role, permission)
    return build_role_response(updated_role)


def remove_permission_from_role(db: Session, role_id: int, permission_id: int) -> RoleResponse | None:
    role = repository.get_role_by_id(db, role_id)
    if role is None:
        return None
    permission = repository.get_permission_by_id(db, permission_id)
    if permission is None:
        raise LookupError("Permission not found")
    if not any(existing_permission.id == permission.id for existing_permission in role.permissions):
        raise ValueError("El rol no tiene asignado ese permiso")
    updated_role = repository.remove_permission_from_role(db, role, permission)
    return build_role_response(updated_role)


def get_role_permissions(db: Session, role_id: int) -> list[PermissionResponse] | None:
    role = repository.get_role_by_id(db, role_id)
    if role is None:
        return None
    permissions = sorted(role.permissions, key=lambda item: item.id)
    return [PermissionResponse.model_validate(permission) for permission in permissions]


def authenticate_user(db: Session, username: str, password: str) -> InternalUser | None:
    user = repository.get_user_by_username(db, username)
    if user is None:
        return None
    if not user.is_active:
        raise ValueError("Usuario interno inactivo")
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_user_permission_codes(user: InternalUser) -> set[str]:
    codes: set[str] = set()
    for role in user.roles:
        if not role.is_active:
            continue
        for permission in role.permissions:
            codes.add(permission.code)
    return codes


def build_user_response(user: InternalUser) -> UserResponse:
    active_roles = sorted((role for role in user.roles if role.is_active), key=lambda item: item.name)
    return UserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        is_active=user.is_active,
        roles=[role.name for role in active_roles],
        permissions=sorted(get_user_permission_codes(user)),
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def build_role_response(role: Role) -> RoleResponse:
    permissions = sorted((permission.code for permission in role.permissions))
    return RoleResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        is_active=role.is_active,
        permissions=permissions,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


def seed_initial_access_control(db: Session) -> AssignmentResponse:
    permissions_by_code: dict[str, Permission] = {}
    for permission_data in BASE_PERMISSIONS:
        permission = repository.get_permission_by_code(db, permission_data["code"])
        if permission is None:
            permission = repository.create_permission(db, PermissionCreate(**permission_data))
        permissions_by_code[permission.code] = permission

    roles_by_name: dict[str, Role] = {}
    for role_name, permission_codes in BASE_ROLE_PERMISSIONS.items():
        role = repository.get_role_by_name(db, role_name)
        if role is None:
            role = repository.create_role(
                db,
                RoleCreate(
                    name=role_name,
                    description=BASE_ROLE_DESCRIPTIONS.get(role_name),
                    is_active=True,
                ),
            )
        roles_by_name[role.name] = role

        existing_codes = {permission.code for permission in role.permissions}
        for permission_code in permission_codes:
            if permission_code in existing_codes:
                continue
            repository.assign_permission_to_role(db, role, permissions_by_code[permission_code])
            role = repository.get_role_by_id(db, role.id)

        desired_codes = set(permission_codes)
        if role.name == "ESTIBA":
            permissions_to_remove = [
                permission
                for permission in role.permissions
                if permission.code not in desired_codes
            ]
        else:
            permissions_to_remove = [
                permission
                for permission in role.permissions
                if permission.code.startswith("optimization.")
                and permission.code not in desired_codes
            ]

        for permission in permissions_to_remove:
            repository.remove_permission_from_role(db, role, permission)
            role = repository.get_role_by_id(db, role.id)

    admin = repository.get_user_by_username(db, settings.default_admin_username)
    if admin is None:
        admin = repository.create_user(
            db,
            UserCreate(
                username=settings.default_admin_username,
                password=settings.default_admin_password,
                full_name="Administrador del Sistema",
            ),
            hash_password(settings.default_admin_password),
        )

    admin_role = roles_by_name["ADMINISTRADOR"]
    if not any(role.id == admin_role.id for role in admin.roles):
        repository.assign_role_to_user(db, admin, admin_role)

    return AssignmentResponse(success=True, message="Seed inicial de usuarios, roles y permisos verificado")


def _ensure_username_available(db: Session, username: str) -> None:
    if repository.get_user_by_username(db, username) is not None:
        raise ValueError("username already exists")


def _ensure_role_name_available(db: Session, name: str) -> None:
    if repository.get_role_by_name(db, name) is not None:
        raise ValueError("role name already exists")


def _ensure_permission_code_available(db: Session, code: str) -> None:
    if repository.get_permission_by_code(db, code) is not None:
        raise ValueError("permission code already exists")
