import os

from dotenv import load_dotenv

load_dotenv()

# LLM & Pipeline Settings
def get_local_whisper_model() -> str:
    load_dotenv(override=True)
    val = os.getenv("LOCAL_WHISPER_MODEL", "").strip()
    return val if val else "base"


def get_local_whisper_device() -> str:
    load_dotenv(override=True)
    val = os.getenv("LOCAL_WHISPER_DEVICE", "").strip()
    return val if val else "auto"  # auto / cpu / cuda


def get_local_output_dir() -> str:
    load_dotenv(override=True)
    val = os.getenv("LOCAL_OUTPUT_DIR", "").strip()
    return val if val else "output"


def get_llm_provider() -> str:
    load_dotenv(override=True)
    val = os.getenv("LLM_PROVIDER", "").strip().lower()
    return val if val else "openai"


def get_openai_model() -> str:
    load_dotenv(override=True)
    val = os.getenv("OPENAI_MODEL", "").strip()
    return val if val else "gpt-4o-mini"


def get_gemini_model() -> str:
    load_dotenv(override=True)
    val = os.getenv("GEMINI_MODEL", "").strip()
    return val if val else "gemini-2.5-flash"


def get_ollama_model() -> str:
    load_dotenv(override=True)
    val = os.getenv("OLLAMA_MODEL", "").strip()
    return val if val else "gemma4:e4b"


def get_ollama_base_url() -> str:
    load_dotenv(override=True)
    val = os.getenv("OLLAMA_BASE_URL", "").strip()
    return val if val else "http://localhost:11434"


def get_groq_model() -> str:
    load_dotenv(override=True)
    val = os.getenv("GROQ_MODEL", "").strip()
    return val if val else "llama-3.3-70b-versatile"


def require_openai_key() -> str:
    load_dotenv(override=True)
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Please add it to your .env or configure it in the dashboard settings."
        )
    return key


def require_gemini_key() -> str:
    load_dotenv(override=True)
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Please add it to your .env or configure it in the dashboard settings."
        )
    return key


_cancelled = False


def is_cancelled() -> bool:
    global _cancelled
    return _cancelled


def cancel_generation():
    global _cancelled
    _cancelled = True


def reset_cancel():
    global _cancelled
    _cancelled = False
