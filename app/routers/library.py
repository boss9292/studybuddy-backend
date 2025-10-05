from __future__ import annotations

import uuid
import httpx
from fastapi import APIRouter, HTTPException, Header
from loguru import logger

from ..settings import settings
from ..auth import user_id_from_auth_header

router = APIRouter()

SB_REST = f"{settings.SUPABASE_URL}/rest/v1"
SB_HEADERS = {
    "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
}

def _as_uuid(val: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(val))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid UUID")

async def _owner_check(table: str, row_id: str, uid: str) -> None:
    """Ensure the row belongs to uid (using service role but verifying manually)."""
    params = {"id": f"eq.{row_id}", "select": "id,user_id", "limit": "1"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{SB_REST}/{table}", headers=SB_HEADERS, params=params)
    if r.status_code >= 300:
        raise HTTPException(status_code=500, detail=f"Supabase read failed: {r.text}")
    rows = r.json()
    if not rows:
        raise HTTPException(status_code=404, detail="Not found")
    if rows[0].get("user_id") != uid:
        raise HTTPException(status_code=403, detail="Forbidden")

@router.delete("/library/documents/{doc_id}")
async def delete_document(doc_id: str, Authorization: str | None = Header(default=None)):
    uid = user_id_from_auth_header(Authorization)
    if not uid:
        raise HTTPException(status_code=401, detail="Missing/invalid token")

    _ = _as_uuid(doc_id)  # validate format
    await _owner_check("documents", doc_id, uid)

    async with httpx.AsyncClient(timeout=30) as client:
        # delete quizzes first (if FK isn't ON DELETE CASCADE)
        dq = await client.delete(f"{SB_REST}/quizzes", headers=SB_HEADERS, params={"doc_id": f"eq.{doc_id}"})
        if dq.status_code >= 300:
            logger.warning(f"[delete] quizzes cleanup failed: {dq.status_code} {dq.text}")

        dd = await client.delete(f"{SB_REST}/documents", headers=SB_HEADERS, params={"id": f"eq.{doc_id}"})
        if dd.status_code >= 300:
            raise HTTPException(status_code=500, detail=f"Delete document failed: {dd.text}")

    return {"deleted": True, "id": doc_id}

@router.delete("/library/quizzes/{quiz_id}")
async def delete_quiz(quiz_id: str, Authorization: str | None = Header(default=None)):
    uid = user_id_from_auth_header(Authorization)
    if not uid:
        raise HTTPException(status_code=401, detail="Missing/invalid token")

    _ = _as_uuid(quiz_id)  # validate format
    await _owner_check("quizzes", quiz_id, uid)

    async with httpx.AsyncClient(timeout=15) as client:
        dq = await client.delete(f"{SB_REST}/quizzes", headers=SB_HEADERS, params={"id": f"eq.{quiz_id}"})
        if dq.status_code >= 300:
            raise HTTPException(status_code=500, detail=f"Delete quiz failed: {dq.text}")

    return {"deleted": True, "id": quiz_id}
