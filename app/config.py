import os
from dotenv import load_dotenv

load_dotenv(override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MOCK_MODE = os.getenv("MOCK_MODE") == "1"

MAX_PAGES = int(os.getenv("MAX_PAGES", "30"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "4"))

# Add your deployed frontend origin later
ALLOW_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
fe = os.getenv("FRONTEND_ORIGIN", "").strip()
if fe:
    ALLOW_ORIGINS.append(fe)
