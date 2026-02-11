from __future__ import annotations

import json
import uuid
from typing import Optional, Dict, Any

import httpx
from fastapi import FastAPI, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi import _rate_limit_exceeded_handler
from starlette.responses import Response

from .settings import settings
from .auth import user_id_from_auth_header
from .routers import upload, quiz, export, debug
from .routers import library  # <-- new delete endpoints

# ---------- logging ----------
logger.remove()
logger.add(
    lambda msg: print(msg, end=""),
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
    level="INFO",
)

# ---------- app / limiter ----------
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT])
app = FastAPI(title="StudyBuddy API", version="1.0.0")
app.state.limiter = limiter

# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "Authorization", "Content-Type", "X-Requested-With"],
    expose_headers=["Authorization"],
)

# SlowAPI middleware + handler
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---------- Supabase REST (service role) for post-save ----------
SB_REST = f"{settings.SUPABASE_URL}/rest/v1"
SB_HEADERS = {
    "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
}

def _is_uuid(val: Optional[str]) -> bool:
    if not val: return False
    try:
        uuid.UUID(str(val)); return True
    except Exception:
        return False

async def _save_document(user_id: str, payload: Dict[str, Any]) -> bool:
    body = {
        "user_id": user_id,
        "title": payload.get("title") or "Untitled",
        "summary": payload.get("summary") or "",
        "cards_json": (
            payload.get("cards_json")
            if isinstance(payload.get("cards_json"), str)
            else json.dumps(payload.get("cards") or {"cards": []}, ensure_ascii=False)
        ),
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{SB_REST}/documents",
            headers={**SB_HEADERS, "Prefer": "return=minimal"},
            json=body,
        )
    ok = r.status_code < 300
    if not ok:
        logger.warning(f"[postsave] documents insert failed: {r.status_code} {r.text}")
    return ok

async def _get_recent_document_id_by_title(user_id: str, title: str) -> Optional[str]:
    params = {
        "user_id": f"eq.{user_id}",
        "title": f"eq.{title}",
        "select": "id",
        "order": "created_at.desc",
        "limit": "1",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{SB_REST}/documents", headers=SB_HEADERS, params=params)
    if r.status_code >= 300:
        logger.warning(f"[postsave] fetch recent doc failed: {r.status_code} {r.text}")
        return None
    items = r.json()
    if items:
        return items[0].get("id")
    return None

async def _create_document_stub(user_id: str, title: str) -> Optional[str]:
    body = {
        "user_id": user_id,
        "title": title or "Untitled",
        "summary": "",
        "cards_json": json.dumps({"cards": []}, ensure_ascii=False),
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{SB_REST}/documents",
            headers={**SB_HEADERS, "Prefer": "return=representation"},
            json=body,
        )
    if r.status_code >= 300:
        logger.warning(f"[postsave] create stub document failed: {r.status_code} {r.text}")
        return None
    try:
        return r.json()[0]["id"]
    except Exception:
        return None

async def _save_quiz(user_id: str, payload: Dict[str, Any]) -> bool:
    """
    Save a quiz ONLY. Do NOT create a document stub.
    If a valid doc_id is provided (or resolvable), we link it; otherwise we save the quiz without doc_id.
    """
    # 1) Try to use the provided doc_id/document_id
    doc_id = payload.get("document_id") or payload.get("doc_id")
    if not _is_uuid(doc_id):
        # 2) (Optional) try to link to an existing document by title — but DO NOT create one
        title = payload.get("title") or "Untitled"
        found = await _get_recent_document_id_by_title(user_id, title)
        doc_id = found if _is_uuid(found) else None

    # Build quiz_json string from payload
    quiz_json_str = (
        payload.get("quiz_json")
        if isinstance(payload.get("quiz_json"), str)
        else json.dumps(payload.get("quiz") or {"questions": []}, ensure_ascii=False)
    )

    try:
        nq = payload.get("num_questions")
        if not isinstance(nq, int):
            nq = len((json.loads(quiz_json_str) or {}).get("questions", []))
    except Exception:
        nq = None

    body: Dict[str, Any] = {
        "user_id": user_id,
        "title": payload.get("title") or "Untitled",
        "quiz_json": quiz_json_str,
        "num_questions": nq,
    }
    # Only include doc_id if we truly have a valid UUID
    if _is_uuid(doc_id):
        body["doc_id"] = doc_id

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{SB_REST}/quizzes",
            headers={**SB_HEADERS, "Prefer": "return=minimal"},
            json=body,
        )

    ok = r.status_code < 300
    if not ok:
        logger.warning(f"[postsave] quizzes insert failed: {r.status_code} {r.text}")
    return ok


# ---------- middleware: post-save ----------
@app.middleware("http")
async def save_to_library_after(request: Request, call_next):
    response = await call_next(request)

    target_paths = ("/upload", "/quiz", "/quiz/build")
    if (
        request.method.upper() == "POST"
        and request.url.path in target_paths
        and response.status_code < 300
        and ("application/json" in (response.media_type or "") or "application/json" in response.headers.get("content-type", ""))
    ):
        body_bytes = b""
        async for chunk in response.body_iterator:
            body_bytes += chunk

        new_response = Response(
            content=body_bytes,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

        try:
            payload = json.loads(body_bytes.decode("utf-8") or "{}")
        except Exception:
            return new_response

        auth = request.headers.get("Authorization")
        user_id = None
        try:
            user_id = user_id_from_auth_header(auth)
        except Exception:
            user_id = None

        if not user_id:
            return new_response

        try:
            if request.url.path == "/upload":
                await _save_document(user_id, payload)
            else:
                await _save_quiz(user_id, payload)
        except Exception as e:
            logger.warning(f"[postsave] unexpected error: {e}")

        return new_response

    return response

# ---------- health / whoami ----------
@app.get("/health")
def health():
    return {
        "ok": True,
        "mock": settings.MOCK_MODE,
        "model": settings.OPENAI_MODEL,
        "rate_limit": settings.RATE_LIMIT,
        "max_pages": settings.MAX_PAGES,
        "concurrency": settings.CONCURRENCY,
    }

@app.get("/whoami")
def whoami(Authorization: str | None = Header(default=None)):
    return {"user_id": user_id_from_auth_header(Authorization)}

# ---------- routers ----------
app.include_router(upload.router, tags=["upload"])
app.include_router(quiz.router, tags=["quiz"])
app.include_router(export.router, tags=["export"])
app.include_router(debug.router, tags=["debug"])
app.include_router(library.router, tags=["library"])  # <-- new