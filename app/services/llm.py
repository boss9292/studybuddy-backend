import asyncio, json
from openai import OpenAI
from ..settings import settings

client = OpenAI(api_key=settings.OPENAI_API_KEY) if not settings.MOCK_MODE else None

def _llm_sync(messages, *, max_tokens=400, temperature=0.2):
    if settings.MOCK_MODE:
        sys = (messages[0].get("content","") if messages else "").lower()
        if "flashcards" in sys:
            return '{"cards":[{"type":"definition","front":"What is latency?","back":"Delay before transfer begins.","source":"Slide 3"},{"type":"cloze","front":"TCP handshake is {{c1::SYN}}, {{c2::SYN-ACK}}, {{c3::ACK}}.","back":"SYN → SYN-ACK → ACK","source":"Slide 7"}]}'
        if "questions" in sys:
            return json.dumps({"questions":[{"question":"Which layer handles routing on the Internet?","choices":["Physical","Data Link","Network","Transport"],"answer_index":2,"explanation":"IP routing occurs at Layer 3.","source":"Slide 8"}]})
        return "This is a MOCK summary."
    resp = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content

async def llm(messages, **kw):
    return await asyncio.to_thread(_llm_sync, messages, **kw)
