from fastapi import APIRouter, Request
from fastapi import HTTPException
from ..services.auth import get_user_id_from_auth_header

router = APIRouter()

@router.get("/whoami")
def whoami(request: Request):
    """
    Returns the Supabase user_id if the Authorization header contains a valid token.
    Useful for quickly debugging auth between frontend and backend.
    """
    try:
        user_id = get_user_id_from_auth_header(request.headers.get("Authorization"))
        return {"user_id": user_id}
    except HTTPException:
        return {"user_id": None}
