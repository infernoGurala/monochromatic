import os

from dotenv import load_dotenv

load_dotenv()

# LLM & Pipeline Settings
def get_local_whisper_model() -> str:
    load_dotenv(override=True)
    return os.getenv("LOCAL_WHISPER_MODEL", "base").strip()


def get_local_whisper_device() -> str:
    load_dotenv(override=True)
    return os.getenv("LOCAL_WHISPER_DEVICE", "auto").strip()  # auto / cpu / cuda


def get_local_output_dir() -> str:
    load_dotenv(override=True)
    return os.getenv("LOCAL_OUTPUT_DIR", "output").strip()


def get_llm_provider() -> str:
    load_dotenv(override=True)
    return os.getenv("LLM_PROVIDER", "openai").strip().lower()


def get_openai_model() -> str:
    load_dotenv(override=True)
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()


def get_gemini_model() -> str:
    load_dotenv(override=True)
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()


def get_ollama_model() -> str:
    load_dotenv(override=True)
    return os.getenv("OLLAMA_MODEL", "gemma4:e4b").strip()


def get_ollama_base_url() -> str:
    load_dotenv(override=True)
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()


def get_groq_model() -> str:
    load_dotenv(override=True)
    return os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()


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
