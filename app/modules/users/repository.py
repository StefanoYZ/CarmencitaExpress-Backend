from sqlalchemy import asc, or_
from sqlalchemy.orm import Session, selectinload

from app.modules.users.model import InternalUser, Permission, Role
from app.modules.users.schema import PermissionCreate, PermissionUpdate, RoleCreate, RoleUpdate, UserCreate, UserUpdate


def list_users(db: Session) -> list[InternalUser]:
    return (
        db.query(InternalUser)
        .options(selectinload(InternalUser.roles).selectinload(Role.permissions))
        .order_by(asc(InternalUser.id))
        .all()
    )


def get_user_by_id(db: Session, user_id: int) -> InternalUser | None:
    return (
        db.query(InternalUser)
        .options(selectinload(InternalUser.roles).selectinload(Role.permissions))
        .filter(InternalUser.id == user_id)
        .first()
    )


def get_user_by_username(db: Session, username: str) -> InternalUser | None:
    return (
        db.query(InternalUser)
        .options(selectinload(InternalUser.roles).selectinload(Role.permissions))
        .filter(InternalUser.username == username)
        .first()
    )


def get_user_by_email(db: Session, email: str) -> InternalUser | None:
    return (
        db.query(InternalUser)
        .options(selectinload(InternalUser.roles).selectinload(Role.permissions))
        .filter(InternalUser.email == email)
        .first()
    )


def get_user_by_username_or_email(db: Session, value: str) -> InternalUser | None:
    normalized = value.strip().lower()
    return (
        db.query(InternalUser)
        .options(selectinload(InternalUser.roles).selectinload(Role.permissions))
        .filter(or_(InternalUser.username == normalized, InternalUser.email == normalized))
        .first()
    )


def create_user(db: Session, payload: UserCreate, password_hash: str) -> InternalUser:
    user = InternalUser(
        username=payload.username,
        email=payload.email,
        password_hash=password_hash,
        full_name=payload.full_name,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return get_user_by_id(db, user.id)


def update_user(db: Session, user: InternalUser, payload: UserUpdate, password_hash: str | None = None) -> InternalUser:
    update_data = payload.model_dump(exclude_unset=True, exclude={"password"})
    for field, value in update_data.items():
        setattr(user, field, value)
    if password_hash is not None:
        user.password_hash = password_hash
    db.add(user)
    db.commit()
    return get_user_by_id(db, user.id)


def disable_user(db: Session, user: InternalUser) -> InternalUser:
    user.is_active = False
    db.add(user)
    db.commit()
    return get_user_by_id(db, user.id)


def list_roles(db: Session) -> list[Role]:
    return (
        db.query(Role)
        .options(selectinload(Role.permissions))
        .order_by(asc(Role.id))
        .all()
    )


def get_role_by_id(db: Session, role_id: int) -> Role | None:
    return (
        db.query(Role)
        .options(selectinload(Role.permissions))
        .filter(Role.id == role_id)
        .first()
    )


def get_role_by_name(db: Session, name: str) -> Role | None:
    return (
        db.query(Role)
        .options(selectinload(Role.permissions))
        .filter(Role.name == name)
        .first()
    )


def create_role(db: Session, payload: RoleCreate) -> Role:
    role = Role(name=payload.name, description=payload.description, is_active=payload.is_active)
    db.add(role)
    db.commit()
    db.refresh(role)
    return get_role_by_id(db, role.id)


def update_role(db: Session, role: Role, payload: RoleUpdate) -> Role:
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(role, field, value)
    db.add(role)
    db.commit()
    return get_role_by_id(db, role.id)


def disable_role(db: Session, role: Role) -> Role:
    role.is_active = False
    db.add(role)
    db.commit()
    return get_role_by_id(db, role.id)


def list_permissions(db: Session) -> list[Permission]:
    return db.query(Permission).order_by(asc(Permission.id)).all()


def get_permission_by_id(db: Session, permission_id: int) -> Permission | None:
    return db.query(Permission).filter(Permission.id == permission_id).first()


def get_permission_by_code(db: Session, code: str) -> Permission | None:
    return db.query(Permission).filter(Permission.code == code).first()


def create_permission(db: Session, payload: PermissionCreate) -> Permission:
    permission = Permission(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        module=payload.module,
        action=payload.action,
    )
    db.add(permission)
    db.commit()
    db.refresh(permission)
    return permission


def update_permission(db: Session, permission: Permission, payload: PermissionUpdate) -> Permission:
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(permission, field, value)
    db.add(permission)
    db.commit()
    db.refresh(permission)
    return permission


def assign_role_to_user(db: Session, user: InternalUser, role: Role) -> InternalUser:
    user.roles.append(role)
    db.add(user)
    db.commit()
    return get_user_by_id(db, user.id)


def remove_role_from_user(db: Session, user: InternalUser, role: Role) -> InternalUser:
    user.roles.remove(role)
    db.add(user)
    db.commit()
    return get_user_by_id(db, user.id)


def assign_permission_to_role(db: Session, role: Role, permission: Permission) -> Role:
    role.permissions.append(permission)
    db.add(role)
    db.commit()
    return get_role_by_id(db, role.id)


def remove_permission_from_role(db: Session, role: Role, permission: Permission) -> Role:
    role.permissions.remove(permission)
    db.add(role)
    db.commit()
    return get_role_by_id(db, role.id)
