# app/auth.py
from typing import Optional, Any
from jose import jwt, JWTError
import logging
from .settings import settings

logger = logging.getLogger("auth")

def _get_supabase_secret() -> str:
    """
    Return the Supabase JWT secret as a plain string, even if Settings uses SecretStr.
    """
    secret: Any = getattr(settings, "SUPABASE_JWT_SECRET", "")
    if hasattr(secret, "get_secret_value"):
        # pydantic SecretStr
        secret = secret.get_secret_value()
    if not isinstance(secret, str):
        secret = str(secret or "")
    return secret.strip()

def user_id_from_auth_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        logger.warning("No Authorization Bearer token present")
        return None

    token = authorization.split(" ", 1)[1].strip()
    secret = _get_supabase_secret()

    # Debug logs (safe)
    logger.info(f"[auth] Using HS256; secret length={len(secret)}; token prefix={token[:12]}")

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_aud": False},  # Supabase uses 'aud': 'authenticated'
        )
        uid = payload.get("sub") or payload.get("user_id")
        if not uid:
            logger.warning(f"Decoded JWT but no sub/user_id; payload keys: {list(payload.keys())}")
        return uid
    except JWTError as e:
        logger.warning(f"JWT decode failed: {e}")
        return None
