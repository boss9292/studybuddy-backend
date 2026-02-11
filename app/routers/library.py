# app/routers/library.py
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from uuid import UUID
import httpx

from ..settings import settings
from ..auth import user_id_from_auth_header

router = APIRouter(prefix="/library", tags=["library"])

SUPABASE_URL = settings.SUPABASE_URL
SERVICE_KEY = settings.SUPABASE_SERVICE_ROLE_KEY
SR_HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}

async def _get_user_id_from_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1]
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": SERVICE_KEY},
        )
    if r.status_code != 200:
        return None
    return r.json().get("id")

async def _ensure_owner(table: str, row_id: str, user_id: str):
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{row_id}&select=id,user_id",
            headers=SR_HEADERS,
        )
    if r.status_code != 200 or not r.json():
        raise HTTPException(status_code=404, detail="Not found")
    row = r.json()[0]
    if row.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Not your row")

@router.delete("/document/{doc_id}")
async def delete_document(doc_id: str, Authorization: str | None = Header(default=None)):
    try:
        UUID(doc_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid document id")

    # Use your existing JWT decode helper if you want (it’s faster), or stick with the REST call:
    user_id = user_id_from_auth_header(Authorization) or await _get_user_id_from_token(Authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    await _ensure_owner("documents", doc_id, user_id)

    async with httpx.AsyncClient(timeout=30) as client:
        # delete child quizzes first (safe if none)
        await client.delete(
            f"{SUPABASE_URL}/rest/v1/quizzes?doc_id=eq.{doc_id}&user_id=eq.{user_id}",
            headers={**SR_HEADERS, "Prefer": "return=representation"},
        )
        r = await client.delete(
            f"{SUPABASE_URL}/rest/v1/documents?id=eq.{doc_id}&user_id=eq.{user_id}",
            headers={**SR_HEADERS, "Prefer": "return=representation"},
        )

    if r.status_code not in (200, 204):
        raise HTTPException(status_code=400, detail=r.text)
    return {"ok": True}

@router.delete("/quiz/{quiz_id}")
async def delete_quiz(quiz_id: str, Authorization: str | None = Header(default=None)):
    try:
        UUID(quiz_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid quiz id")

    user_id = user_id_from_auth_header(Authorization) or await _get_user_id_from_token(Authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    await _ensure_owner("quizzes", quiz_id, user_id)

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.delete(
            f"{SUPABASE_URL}/rest/v1/quizzes?id=eq.{quiz_id}&user_id=eq.{user_id}",
            headers={**SR_HEADERS, "Prefer": "return=representation"},
        )

    if r.status_code not in (200, 204):
        raise HTTPException(status_code=400, detail=r.text)
    return {"ok": True}
