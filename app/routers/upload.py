from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from openai import APIError, AuthenticationError, RateLimitError
import tempfile, os, json, asyncio
from loguru import logger

from ..services.cache import sha256_bytes, get_payload, save_payload
from ..services.pdf import build_bullets_from_pdf
from ..services.llm import llm
from ..services.parse import parse_cards
from ..services.auth import get_user_id_from_auth_header
from ..services.db import upsert_document
from ..settings import settings

router = APIRouter()

@router.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form("Untitled"),
    make_summary: str = Form("1"),
    make_cards: str = Form("1"),
):
    raw = await file.read()
    if not raw: raise HTTPException(400, "Empty file.")
    if not file.filename.lower().endswith(".pdf"): raise HTTPException(400, "Only PDF supported.")
    if len(raw) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"PDF too large. Max {settings.MAX_UPLOAD_MB} MB.")

    def to_bool(v: str) -> bool: return str(v).lower() in ("1","true","yes","on")
    want_summary, want_cards = to_bool(make_summary), to_bool(make_cards)
    if not (want_summary or want_cards):
        raise HTTPException(400, "Nothing to generate (both flags false).")

    doc_id = sha256_bytes(raw)

    try:
        cached = get_payload(doc_id)
        if want_summary and want_cards: return cached
        return {
            "id": cached.get("id", doc_id),
            "title": cached.get("title", title),
            "summary": cached.get("summary", "") if want_summary else "",
            "cards_json": cached.get("cards_json", "") if want_cards else json.dumps({"cards":[]}),
        }
    except FileNotFoundError:
        pass

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(raw); tmp_path = tmp.name

    try:
        joined, _ = await build_bullets_from_pdf(tmp_path, doc_id)

        summary_task = llm(
            [
                {"role":"system","content":"Combine into a concise, exam-focused summary (10–15 lines, no fluff)."},
                {"role":"user","content": joined[:12000]}
            ],
            max_tokens=450, temperature=0.2
        ) if want_summary else None

        cards_task = llm(
            [
                {"role":"system","content":(
                    "Return only valid JSON with no extra text. "
                    "Schema: {\"cards\":[{\"type\":\"definition|cloze|qa|formula\",\"front\":\"...\",\"back\":\"...\",\"source\":\"Slide X\"}]}")},
                {"role":"user","content": f"Create 20–30 high-yield flashcards from these bullets:\n{joined[:12000]}"}
            ],
            max_tokens=1500, temperature=0.2
        ) if want_cards else None

        summary = ""
        cards_json_str = json.dumps({"cards":[]})

        if want_summary and want_cards:
            s_raw, c_raw = await asyncio.gather(summary_task, cards_task)
            summary = s_raw
            try:
                cards_obj = parse_cards(c_raw)
            except Exception:
                from ..services.llm import llm as fix_llm
                repaired = await fix_llm(
                    [
                        {"role":"system","content":"Fix to valid JSON {cards:[{type,front,back,source}]} only. No prose."},
                        {"role":"user","content": c_raw}
                    ],
                    max_tokens=1500
                )
                cards_obj = parse_cards(repaired)
            cards_json_str = json.dumps(cards_obj, ensure_ascii=False)
        elif want_summary:
            summary = await summary_task
        elif want_cards:
            c_raw = await cards_task
            try:
                cards_obj = parse_cards(c_raw)
            except Exception:
                from ..services.llm import llm as fix_llm
                repaired = await fix_llm(
                    [
                        {"role":"system","content":"Fix to valid JSON {cards:[{type,front,back,source}]} only. No prose."},
                        {"role":"user","content": c_raw}
                    ],
                    max_tokens=1500
                )
                cards_obj = parse_cards(repaired)
            cards_json_str = json.dumps(cards_obj, ensure_ascii=False)

        payload = {"id": doc_id, "title": title, "summary": summary, "cards_json": cards_json_str}
        save_payload(doc_id, payload)

        # Save to Supabase if logged in
        try:
            user_id = get_user_id_from_auth_header(request.headers.get("Authorization"))
            logger.info(f"[upload] Supabase user_id={user_id!r} doc_id={doc_id}")
            if user_id:
                upsert_document(
                    user_id=user_id, doc_id=doc_id, title=title,
                    summary=summary, cards_json=cards_json_str
                )
                logger.info(f"[upload] upsert_document ok for user_id={user_id}")
        except HTTPException as e:
            logger.warning(f"[upload] auth error: {e.detail}")

        return payload

    except AuthenticationError:
        raise HTTPException(401, "OpenAI auth failed. Check OPENAI_API_KEY.")
    except RateLimitError:
        raise HTTPException(429, "OpenAI quota/rate limit exceeded.")
    except APIError as e:
        raise HTTPException(502, f"OpenAI API error: {getattr(e, 'message', str(e))}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Server error: {str(e)}")
    finally:
        try: os.remove(tmp_path)
        except: pass
