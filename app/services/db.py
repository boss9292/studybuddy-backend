from supabase import create_client, Client
from ..settings import settings

_supabase: Client | None = None

def supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _supabase

def upsert_document(*, user_id: str, doc_id: str, title: str, summary: str, cards_json: str):
    sb = supabase()
    sb.table("documents").upsert({
        "id": doc_id,
        "user_id": user_id,
        "title": title,
        "summary": summary,
        "cards_json": cards_json,
    }, on_conflict="id").execute()

def insert_quiz(*, user_id: str, doc_id: str, title: str, quiz_json: str, num_questions: int):
    sb = supabase()
    sb.table("quizzes").insert({
        "doc_id": doc_id,
        "user_id": user_id,
        "title": title,
        "quiz_json": quiz_json,
        "num_questions": num_questions,
    }).execute()
