from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

from app.core.config import settings


PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "$".join(
        [
            PASSWORD_ALGORITHM,
            str(PASSWORD_ITERATIONS),
            _b64encode(salt),
            _b64encode(digest),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = _b64decode(salt_text)
        expected_digest = _b64decode(digest_text)
    except (ValueError, TypeError):
        return False

    actual_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual_digest, expected_digest)


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    expire_at = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = data.copy()
    payload["exp"] = int(expire_at.timestamp())

    header = {"alg": settings.algorithm, "typ": "JWT"}
    signing_input = ".".join(
        [
            _b64encode_json(header),
            _b64encode_json(payload),
        ]
    )
    signature = _sign(signing_input)
    return f"{signing_input}.{signature}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header_text, payload_text, signature = token.split(".", 2)
    except ValueError as exc:
        raise ValueError("Invalid token") from exc

    signing_input = f"{header_text}.{payload_text}"
    expected_signature = _sign(signing_input)
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("Invalid token signature")

    header = json.loads(_b64decode(header_text))
    if header.get("alg") != settings.algorithm:
        raise ValueError("Invalid token algorithm")

    payload = json.loads(_b64decode(payload_text))
    exp = payload.get("exp")
    if exp is None or datetime.now(timezone.utc).timestamp() > int(exp):
        raise ValueError("Token expired")
    return payload


def _sign(signing_input: str) -> str:
    digest = hmac.new(settings.secret_key.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


def _b64encode_json(value: dict[str, Any]) -> str:
    payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _b64encode(payload)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))
