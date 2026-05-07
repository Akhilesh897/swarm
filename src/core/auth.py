import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import Header, HTTPException, Request, status

from src.config import get_config
from src.tools import sql


TOKEN_TTL_SECONDS = 60 * 60 * 8
PASSWORD_HASH_ITERATIONS = 260_000


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    email: str
    role: str
    department: str | None = None


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = password_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    ).hex()
    return hmac.compare_digest(digest, expected)


def authenticate_user(email: str, password: str) -> AuthUser | None:
    normalized_email = email.lower().strip()
    row = sql.get_user_by_email(normalized_email)
    if not row or not verify_password(password, row["password_hash"]):
        return None
    role = _resolve_role(normalized_email, row.get("role"))
    if not role:
        return None
    return AuthUser(
        user_id=row["user_id"],
        email=row["email"],
        role=role,
        department=row.get("department"),
    )


def register_user(email: str, password: str) -> tuple[AuthUser | None, str | None]:
    normalized_email = email.lower().strip()
    if not normalized_email or not password:
        return None, "Email and password are required."
    if "@" not in normalized_email:
        return None, "Enter a valid email address."
    if len(password) < 6:
        return None, "Password must be at least 6 characters."
    if sql.get_user_by_email(normalized_email):
        return None, "Account already exists. Please login."

    config = get_config()
    role = _normalize_role(config.admin_email_roles.get(normalized_email, "employee"))
    department = "it" if role == "it_lead" else None
    created = sql.create_user(
        user_id=f"user_{uuid4().hex[:8]}",
        email=normalized_email,
        role=role,
        password=password,
        department=department,
    )
    return (
        AuthUser(
            user_id=created["user_id"],
            email=created["email"],
            role=created["role"],
            department=created.get("department"),
        ),
        None,
    )


def create_access_token(user: AuthUser) -> str:
    now = int(time.time())
    payload = {
        "sub": user.user_id,
        "email": user.email,
        "role": user.role,
        "department": user.department,
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
    }
    return _encode_jwt(payload)


def decode_access_token(token: str) -> AuthUser:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".", 2)
    except ValueError as exc:
        raise _invalid_token() from exc

    signed = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = _sign(signed)
    if not hmac.compare_digest(_b64encode(expected), signature_b64):
        raise _invalid_token()

    payload = _json_loads_b64(payload_b64)
    expires_at = int(payload.get("exp", 0))
    if expires_at < int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = str(payload.get("sub", "")).strip()
    email = str(payload.get("email", "")).strip()
    role = str(payload.get("role", "")).strip()
    if not user_id or not email or not role:
        raise _invalid_token()
    department = payload.get("department")
    return AuthUser(
        user_id=user_id,
        email=email,
        role=role,
        department=str(department) if department else None,
    )


def require_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> AuthUser:
    user = _parse_authorization(authorization, allow_missing=False)
    if not user:
        raise _invalid_token()
    return user


def require_pa_callback(
    request: Request,
    x_pa_secret: str | None = Header(default=None, alias="X-PA-Secret"),
) -> None:
    """Dependency for the Power Automate callback endpoint /approvals/it.

    Validates the shared secret sent in the ``X-PA-Secret`` header.
    If ``PA_CALLBACK_SECRET`` is not configured the check is skipped so
    local / dev environments work out-of-the-box.
    """
    import logging
    logging.getLogger(__name__).debug(
        "[PA-CALLBACK] %s %s  X-PA-Secret present=%s",
        request.method,
        request.url.path,
        x_pa_secret is not None,
    )
    expected = get_config().pa_callback_secret
    if not expected:
        # PA_CALLBACK_SECRET not configured — allow all (dev/local mode)
        return
    if not x_pa_secret or not hmac.compare_digest(x_pa_secret, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing PA callback secret",
        )


def _encode_jwt(payload: dict[str, Any]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _json_dumps_b64(header)
    payload_b64 = _json_dumps_b64(payload)
    signature = _sign(f"{header_b64}.{payload_b64}".encode("ascii"))
    return f"{header_b64}.{payload_b64}.{_b64encode(signature)}"


def _sign(message: bytes) -> bytes:
    secret = get_config().jwt_secret.encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).digest()


def _json_dumps_b64(value: dict[str, Any]) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _b64encode(raw)


def _json_loads_b64(value: str) -> dict[str, Any]:
    try:
        return json.loads(_b64decode(value))
    except (ValueError, json.JSONDecodeError) as exc:
        raise _invalid_token() from exc


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _invalid_token() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _parse_authorization(authorization: str | None, allow_missing: bool) -> AuthUser | None:
    if not authorization:
        if allow_missing:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _invalid_token()
    return decode_access_token(token)


def _resolve_role(email: str, stored_role: str | None) -> str | None:
    normalized_email = email.strip().lower()
    config = get_config()
    if normalized_email in config.admin_email_roles:
        return _normalize_role(config.admin_email_roles[normalized_email])
    if stored_role:
        return _normalize_role(stored_role)
    if normalized_email.endswith(f"@{config.company_email_domain}"):
        return "employee"
    return None


def _normalize_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized == "it":
        return "it_lead"
    return normalized
