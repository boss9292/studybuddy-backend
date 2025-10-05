from typing import List, Optional
from pydantic import BaseModel

class Card(BaseModel):
    type: Optional[str] = "qa"
    front: str
    back: str
    source: Optional[str] = None

class CardSet(BaseModel):
    cards: List[Card]

class MCQ(BaseModel):
    question: str
    choices: List[str]
    answer_index: int
    explanation: str
    source: Optional[str] = None

class QuizSet(BaseModel):
    questions: List[MCQ]
