from sqlalchemy.orm import Session

from app.modules.integration_settings.model import IntegrationSettings


def get_integration_settings(db: Session) -> IntegrationSettings:
    config = db.get(IntegrationSettings, 1)
    if config is None:
        config = IntegrationSettings(id=1)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def update_integration_settings(
    db: Session,
    *,
    mercadopago_enabled: bool,
    lycet_enabled: bool,
) -> IntegrationSettings:
    config = get_integration_settings(db)
    config.mercadopago_enabled = mercadopago_enabled
    config.lycet_enabled = lycet_enabled
    db.commit()
    db.refresh(config)
    return config


def mercadopago_flow_enabled(db: Session) -> bool:
    return bool(get_integration_settings(db).mercadopago_enabled)


def lycet_flow_enabled(db: Session) -> bool:
    return bool(get_integration_settings(db).lycet_enabled)
