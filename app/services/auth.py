from typing import Optional
import jwt  # PyJWT
from fastapi import HTTPException
from ..settings import settings

def get_user_id_from_auth_header(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(401, "Invalid Authorization header")
    token = parts[1]
    try:
        payload = jwt.decode(token, settings.SUPABASE_JWT_SECRET, algorithms=["HS256"])
        return payload.get("sub")
    except Exception:
        raise HTTPException(401, "Invalid Supabase token")
