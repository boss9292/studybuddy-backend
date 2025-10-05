import re, asyncio
import fitz  # PyMuPDF
from fastapi import HTTPException
from ..settings import settings
from .llm import llm
from .cache import read_bullets, save_bullets

def extract_pages_text(pdf_path: str) -> list[str]:
    doc = fitz.open(pdf_path)
    out = []
    for p in doc:
        t = p.get_text() or ""
        t = re.sub(r"[ \t]+", " ", t).strip()
        out.append(t)
    return out

async def build_bullets_from_pdf(tmp_path: str, doc_id: str) -> tuple[str, list[str]]:
    cached = read_bullets(doc_id)
    if cached:
        return cached["joined"], cached["bullets"]

    pages = extract_pages_text(tmp_path)
    if not any(p.strip() for p in pages):
        raise HTTPException(422, "No extractable text found (image-only PDF).")

    sem = asyncio.Semaphore(settings.CONCURRENCY)

    async def one(idx: int, txt: str):
        if not txt: return None
        snippet = txt[:1500]
        async with sem:
            b = await llm(
                [
                    {"role":"system","content":"Return 3–6 dense, exam-focused bullets. No preface, no conclusion."},
                    {"role":"user","content": f"Slide {idx} text:\n{snippet}"}
                ],
                max_tokens=220, temperature=0.2
            )
            return f"Slide {idx}:\n{b}"

    tasks = [one(i, t) for i, t in enumerate(pages[:settings.MAX_PAGES], start=1)]
    results = [r for r in await asyncio.gather(*tasks) if r]
    joined = "\n\n".join(results) if results else "No text found."

    save_bullets(doc_id, joined, results)
    return joined, results
