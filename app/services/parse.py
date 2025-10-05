import json, re
from pydantic import ValidationError
from ..schemas import CardSet, QuizSet

def _clean(s: str) -> str:
    return re.sub(r"```(json|JSON)?|```", "", s or "").strip()

def parse_cards(s: str) -> dict:
    data = json.loads(_clean(s))
    return CardSet.model_validate(data).model_dump()

def parse_quiz(s: str) -> dict:
    data = json.loads(_clean(s))
    quiz = QuizSet.model_validate(data)
    for q in quiz.questions:
        if len(q.choices) != 4:
            raise ValidationError.from_exception_data("MCQ", [{"msg": "exactly 4 choices", "loc": ("choices",)}])
        if q.answer_index not in (0,1,2,3):
            raise ValidationError.from_exception_data("MCQ", [{"msg": "answer_index 0..3", "loc": ("answer_index",)}])
    return quiz.model_dump()
