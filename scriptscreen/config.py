import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache"
OUT_DIR = ROOT / "output"

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "llama-3.3-70b-versatile")

# Free key from enter.pollinations.ai (image generation now needs one)
POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY", "")

# Magic Hour: real AI video clips. AI_CLIPS_MAX = how many scenes PER AUDIENCE get a generated clip
# (the rest use the Ken Burns animation). One clip costs ~120 credits, so raise this only when you have credits.
MAGIC_HOUR_API_KEY = os.getenv("MAGIC_HOUR_API_KEY", "")
MAGIC_HOUR_MODEL = os.getenv("MAGIC_HOUR_MODEL", "ltx-2.5")
MAGIC_HOUR_RES = os.getenv("MAGIC_HOUR_RES", "480p")
AI_CLIPS_MAX = int(os.getenv("AI_CLIPS_MAX", "1"))

# True = no network calls at all (last-resort demo mode)
OFFLINE = os.getenv("OFFLINE", "0") == "1"

# One consistent definition of video length (the brief gives three different ones)
TARGET_SECONDS = 45
MIN_SECONDS, MAX_SECONDS = 30, 60

FORMATS = {
    "horizontal": (1280, 720),   # YouTube
    "vertical": (720, 1280),     # Reels / Shorts
    "square": (1080, 1080),      # LinkedIn
}
