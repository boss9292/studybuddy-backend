from pathlib import Path
import json, hashlib
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def _write_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

def get_payload(doc_id: str):
    p = CACHE_DIR / f"{doc_id}.json"
    if not p.exists():
        raise FileNotFoundError
    return _read_json(p)

def save_payload(doc_id: str, payload: dict):
    _write_json(CACHE_DIR / f"{doc_id}.json", payload)

def read_bullets(doc_id: str) -> Optional[dict]:
    p = CACHE_DIR / f"{doc_id}.bullets.json"
    return _read_json(p) if p.exists() else None

def save_bullets(doc_id: str, joined: str, bullets: list[str]):
    _write_json(CACHE_DIR / f"{doc_id}.bullets.json", {"joined": joined, "bullets": bullets})

def read_quiz(doc_id: str) -> Optional[dict]:
    p = CACHE_DIR / f"{doc_id}.quiz.json"
    return _read_json(p) if p.exists() else None

def save_quiz(doc_id: str, payload: dict):
    _write_json(CACHE_DIR / f"{doc_id}.quiz.json", payload)
