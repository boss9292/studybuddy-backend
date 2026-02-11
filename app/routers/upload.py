from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from openai import APIError, AuthenticationError, RateLimitError
import tempfile, os, json, asyncio, re
from loguru import logger

# local services you already have
from ..services.cache import sha256_bytes  # stable doc id (not used for caching results)
from ..services.pdf import build_bullets_from_pdf
from ..services.llm import llm
from ..services.parse import parse_cards
from ..services.auth import get_user_id_from_auth_header
from ..services.db import upsert_document
from ..settings import settings

router = APIRouter()

# ---------------------------
# Helpers
# ---------------------------

def chunk_text(s: str, max_chars: int = 9000):
    """Paragraph-preserving chunker."""
    parts, cur, n = [], [], 0
    for para in s.split("\n"):
        if n + len(para) + 1 > max_chars and cur:
            parts.append("\n".join(cur))
            cur, n = [], 0
        cur.append(para)
        n += len(para) + 1
    if cur:
        parts.append("\n".join(cur))
    return parts

def normalize_markdown_final(md: str) -> str:
    """
    Normalize & pretty-format Markdown so both app and export render the same:
      - remove BOM/zero-widths; convert exotic spaces to normal
      - normalize newlines
      - ensure tokens (#, -, *, +, 1., >, |) are at column 0
      - remove orphan '##' lines
      - ensure blank lines around headings and lists
      - collapse >2 newlines
    """
    if not md:
        return ""
    s = md
    s = s.replace("\uFEFF", "")
    s = re.sub(r"[\u200B-\u200D\u2060]", "", s)
    s = re.sub(r"[\u00A0\u1680\u180E\u2000-\u200A\u202F\u205F\u3000]", " ", s)
    s = re.sub(r"\r\n?", "\n", s)

    s = re.sub(
        r"^[ \t\u00A0\u1680\u180E\u2000-\u200A\u202F\u205F\u3000]+(?=(#{1,6}\s|[-*+]\s|\d+\.\s|>\s|\|))",
        "",
        s,
        flags=re.M,
    )
    s = re.sub(r"^\s*#{1,6}\s*$", "", s, flags=re.M)

    s = re.sub(r"([^\n])\n(#{1,6}\s)", r"\1\n\n\2", s)        # before H1–H6
    s = re.sub(r"(#{1,6}\s[^\n]+)\n(?!\n)", r"\1\n\n", s)     # after H1–H6
    s = re.sub(r"([^\n])\n([-*+]\s|\d+\.\s)", r"\1\n\n\2", s) # before list
    s = re.sub(r"((?:^|\n)(?:[-*+]\s|\d+\.\s).*(?:\n(?:[-*+]\s|\d+\.\s).*)*)\n([^\n-])", r"\1\n\n\2", s)

    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

# ---------------------------
# Document-aware outline prompts
# ---------------------------

OUTLINE_SYS = (
    "Propose a clean, document-aware outline for study notes based ONLY on the provided text.\n"
    "Return valid JSON only. Schema: {\"sections\":[{\"title\":\"...\"}]}\n"
    "8–14 concise section titles; reflect the actual content; do not inject unrelated topics."
)

async def infer_outline(joined: str) -> list[str]:
    raw = await llm(
        [
            {"role": "system", "content": OUTLINE_SYS},
            {"role": "user", "content": joined[:16000]},
        ],
        max_tokens=800,
        temperature=0.2,
    )
    try:
        data = json.loads(raw)
        titles = [s.get("title", "").strip() for s in data.get("sections", []) if s.get("title")]
        titles = [t for t in titles if len(t) >= 3][:14]
        if titles:
            return titles
    except Exception:
        pass
    # Fallback generic outline
    return [
        "Introduction / Overview",
        "Key Definitions and Concepts",
        "Core Ideas and Intuition",
        "Detailed Explanations and Worked Examples",
        "Methods / Algorithms / Procedures",
        "Parameters, Tuning, and Trade-offs",
        "Common Pitfalls and Edge Cases",
        "Rules of Thumb and Formulas",
        "Applications / Case Studies",
        "Summary and Review Points",
        "Practice Questions / Self-Check",
    ]

def map_md_prompt(word_target: int, section_titles: list[str]) -> str:
    bul = "\n".join([f"- {t}" for t in section_titles])
    return (
        "Write polished study notes in MARKDOWN for the provided chunk ONLY.\n"
        "Formatting:\n"
        "- Each topic/section MUST start with a Markdown heading: '## Topic Name' (no H1 here).\n"
        "- Use the following section names as headings when present:\n"
        f"{bul}\n"
        "- Add one blank line before and after each '##' heading.\n"
        "- Use short paragraphs with a blank line between them.\n"
        "- Use '-' lists for definitions, concepts, or examples, with a blank line before and after lists.\n"
        "- Bold key vocabulary with **term**.\n"
        f"- Be detailed; total target across all chunks is ~{word_target} words.\n"
        "- Do NOT use plain text for section titles; always use Markdown headings.\n"
        "Content must come only from the provided text."
    )

def reduce_md_prompt(word_target: int, title: str, section_titles: list[str]) -> str:
    sec = "\n".join([f"- {t}" for t in section_titles])
    return (
        "Merge fragments into ONE cohesive MARKDOWN document with these rules:\n"
        f"- First line must be an H1 title: '# {title}'.\n"
        "- After the title, add one blank line.\n"
        "- Use '## ' for sections; prefer this order when relevant:\n"
        f"{sec}\n"
        "- Keep paragraphs short; bold important terms; add blank lines around headings and lists.\n"
        f"- Aim for {word_target} words (±20%).\n"
        "Use only the provided content; do not introduce unrelated topics."
    )

async def make_study_notes_markdown(joined: str, title: str, word_target: int) -> str:
    sections = await infer_outline(joined)
    chunks = chunk_text(joined, max_chars=9000)

    map_tasks = [
        llm(
            [
                {"role": "system", "content": map_md_prompt(word_target, sections)},
                {"role": "user", "content": chunk},
            ],
            max_tokens=2600,
            temperature=0.25,
        )
        for chunk in chunks
    ]
    mapped = await asyncio.gather(*map_tasks)

    merged = await llm(
        [
            {"role": "system", "content": reduce_md_prompt(word_target, title, sections)},
            {"role": "user", "content": "\n\n---\n\n".join(mapped)},
        ],
        max_tokens=7200,
        temperature=0.25,
    )
    return normalize_markdown_final(merged)

# ---------------------------
# Route
# ---------------------------

@router.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form("Comprehensive Study Notes"),
    make_summary: str = Form("1"),
    make_cards: str = Form("1"),
    word_target: int = Form(3000),
):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file.")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF supported.")
    if len(raw) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"PDF too large. Max {settings.MAX_UPLOAD_MB} MB.")

    to_bool = lambda v: str(v).lower() in ("1", "true", "yes", "on")
    want_summary, want_cards = to_bool(make_summary), to_bool(make_cards)
    if not (want_summary or want_cards):
        raise HTTPException(400, "Nothing to generate (both flags false).")

    doc_id = sha256_bytes(raw)  # stable id for persistence (not for reuse/caching of text)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        # Extract doc bullets strictly from THIS PDF
        joined, _ = await build_bullets_from_pdf(tmp_path, doc_id)

        summary_task = None
        if want_summary:
            target = max(2200, min(6000, int(word_target)))
            final_title = title
            summary_task = make_study_notes_markdown(joined, final_title, target)

        cards_task = None
        if want_cards:
            cards_task = llm(
                [
                    {"role": "system", "content": (
                        "Return only valid JSON (no prose). "
                        'Schema: {"cards":[{"type":"definition|cloze|qa|formula","front":".","back":".","source":"Page X"}]}'
                    )},
                    {"role": "user", "content": "Create 24–34 high-yield flashcards based ONLY on the following text:\n\n" + joined[:16000]},
                ],
                max_tokens=1700,
                temperature=0.2,
            )

        summary = ""
        cards_json_str = json.dumps({"cards": []}, ensure_ascii=False)

        if want_summary and want_cards:
            s_raw, c_raw = await asyncio.gather(summary_task, cards_task)
            summary = normalize_markdown_final(s_raw)
            try:
                cards_obj = parse_cards(c_raw)
            except Exception:
                repaired = await llm(
                    [
                        {"role": "system", "content": "Fix to valid JSON: {\"cards\":[{\"type\",\"front\",\"back\",\"source\"}]}. No prose."},
                        {"role": "user", "content": c_raw},
                    ],
                    max_tokens=1000,
                    temperature=0,
                )
                cards_obj = parse_cards(repaired)
            cards_json_str = json.dumps(cards_obj, ensure_ascii=False)

        elif want_summary:
            summary = normalize_markdown_final(await summary_task)

        else:
            c_raw = await cards_task
            try:
                cards_obj = parse_cards(c_raw)
            except Exception:
                repaired = await llm(
                    [
                        {"role": "system", "content": "Fix to valid JSON: {\"cards\":[{\"type\",\"front\",\"back\",\"source\"}]}. No prose."},
                        {"role": "user", "content": c_raw},
                    ],
                    max_tokens=1000,
                    temperature=0,
                )
                cards_obj = parse_cards(repaired)
            cards_json_str = json.dumps(cards_obj, ensure_ascii=False)

        payload = {"id": doc_id, "title": title, "summary": summary, "cards_json": cards_json_str}

        # Persist for signed-in users
        try:
            user_id = get_user_id_from_auth_header(request.headers.get("Authorization"))
            if user_id:
                upsert_document(user_id=user_id, doc_id=doc_id, title=title, summary=summary, cards_json=cards_json_str)
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
        try:
            os.remove(tmp_path)
        except:
            pass
