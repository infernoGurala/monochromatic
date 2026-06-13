"""Local LLM backend — OpenAI, Gemini, Ollama, or Groq, selected by LLM_PROVIDER."""
from .config import (
    get_gemini_model,
    get_llm_provider,
    get_openai_model,
    get_ollama_model,
    get_ollama_base_url,
    get_groq_model,
    require_gemini_key,
    require_openai_key,
)


def call_openai_llm(prompt: str) -> str:
    """OpenAI Chat Completions backend used by --mode local."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openai is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    client = OpenAI(api_key=require_openai_key())
    response = client.chat.completions.create(
        model=get_openai_model(),
        temperature=0.7,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def call_gemini_llm(prompt: str) -> str:
    """Gemini backend used by --mode local when LLM_PROVIDER=gemini."""
    try:
        from google import genai  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "google-genai is required for LLM_PROVIDER=gemini. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    client = genai.Client(api_key=require_gemini_key())
    response = client.models.generate_content(
        model=get_gemini_model(),
        contents=prompt,
        config={
            "temperature": 0.2,
            "response_mime_type": "application/json",
            "max_output_tokens": 8192,
        },
    )
    return response.text or ""


def call_ollama_llm(prompt: str) -> str:
    """Ollama backend used by --mode local when LLM_PROVIDER=ollama."""
    import requests

    base_url = get_ollama_base_url().strip()
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        base_url = f"http://{base_url}"
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": get_ollama_model(),
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "options": {
            "temperature": 0.2,
        }
    }
    if "json" in prompt.lower():
        payload["format"] = "json"

    try:
        response = requests.post(url, json=payload, timeout=300)
        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "") or ""
    except Exception as e:
        raise RuntimeError(f"Failed to query Ollama at {url}: {e}") from e


def call_groq_llm(prompt: str) -> str:
    """Groq Chat Completions backend with API key exhaustion auto cycle."""
    import requests
    import os

    # Read keys from API.txt
    keys = []
    if os.path.exists("API.txt"):
        with open("API.txt", "r") as f:
            content = f.read()
            raw_keys = content.replace(",", "\n").split("\n")
            keys = [k.strip() for k in raw_keys if k.strip()]

    if not keys:
        raise RuntimeError(
            "No Groq API keys found. Please save them in the UI settings (saved to API.txt)."
        )

    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": get_groq_model(),
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
    }
    if "json" in prompt.lower():
        payload["response_format"] = {"type": "json_object"}

    last_error = "unknown"
    for i, key in enumerate(keys):
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        print(f"[LLM/Groq] Querying Groq using key {i+1}/{len(keys)} (model: {get_groq_model()})...", flush=True)
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            if response.status_code in (401, 403, 429) or response.status_code >= 500:
                print(f"[LLM/Groq] Key {i+1} failed with status {response.status_code}. Response: {response.text[:200]}", flush=True)
                last_error = f"HTTP {response.status_code}: {response.text[:100]}"
                continue
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"] or ""
        except Exception as e:
            print(f"[LLM/Groq] Key {i+1} raised exception: {e}", flush=True)
            last_error = str(e)
            continue

    raise RuntimeError(f"All Groq API keys exhausted or failed. Last error: {last_error}")


def call_local_llm(prompt: str) -> str:
    """Dispatch to the configured local LLM provider."""
    provider = get_llm_provider()
    if provider == "openai":
        return call_openai_llm(prompt)
    if provider == "gemini":
        return call_gemini_llm(prompt)
    if provider == "ollama":
        return call_ollama_llm(prompt)
    if provider == "groq":
        return call_groq_llm(prompt)
    raise RuntimeError(
        f"Unknown LLM_PROVIDER={provider!r}. Use 'openai', 'gemini', 'ollama', or 'groq'."
    )
