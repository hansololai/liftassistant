"""Unified LLM Caller supporting local Ollama, LiteLLM, and OpenAI-compatible endpoints."""

import json
import logging
from typing import Any, Optional
import urllib.request
import urllib.error

from liftassistant.config import settings

logger = logging.getLogger(__name__)


def call_llm(
    prompt: str,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    json_mode: bool = True,
    timeout: int = 60,
) -> str:
    """Call local Ollama or OpenAI-compatible endpoint directly.
    
    Defaults to local Ollama configured in settings.
    """
    selected_model = model or settings.llm_model
    # Remove 'ollama/' prefix if present for direct Ollama API calls
    clean_model = selected_model.replace("ollama/", "")
    selected_base_url = (base_url or settings.llm_base_url).rstrip("/")
    if "localhost:11434" in selected_base_url:
        selected_base_url = selected_base_url.replace("localhost:11434", "127.0.0.1:11434")

    # If provider is Ollama or base_url contains localhost:11434, use Ollama native endpoint
    if "11434" in selected_base_url or settings.llm_provider == "ollama":
        api_url = f"{selected_base_url}/api/chat"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": clean_model,
            "messages": messages,
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            api_url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                res_body = json.loads(response.read().decode("utf-8"))
                return res_body.get("message", {}).get("content", "").strip()
        except urllib.error.URLError as e:
            logger.error("Failed to connect to Ollama at %s: %s", api_url, e)
            raise ConnectionError(f"Cannot reach Ollama at {api_url}: {e}") from e

    # Fallback to OpenAI-compatible endpoint
    api_url = f"{selected_base_url}/chat/completions"
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": selected_model,
        "messages": messages,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(api_url, data=req_data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_body = json.loads(response.read().decode("utf-8"))
            return res_body["choices"][0]["message"]["content"].strip()
    except urllib.error.URLError as e:
        logger.error("Failed to connect to LLM endpoint at %s: %s", api_url, e)
        raise ConnectionError(f"Cannot reach LLM endpoint at {api_url}: {e}") from e


def call_vision_llm(
    prompt: str,
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    json_mode: bool = True,
    timeout: int = 90,
) -> str:
    """Call multimodal vision LLM (Ollama or OpenAI-compatible) with an image."""
    import base64
    b64_img = base64.b64encode(image_bytes).decode("utf-8")

    selected_model = model or settings.llm_model
    clean_model = selected_model.replace("ollama/", "")
    selected_base_url = (base_url or settings.llm_base_url).rstrip("/")
    if "localhost:11434" in selected_base_url:
        selected_base_url = selected_base_url.replace("localhost:11434", "127.0.0.1:11434")

    # 1. Native Ollama vision API
    if "11434" in selected_base_url or settings.llm_provider == "ollama":
        vision_model = clean_model
        if "tools" in vision_model:
            vision_model = "gemma3:latest"

        api_url = f"{selected_base_url}/api/chat"
        payload: dict[str, Any] = {
            "model": vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [b64_img],
                }
            ],
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            api_url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                res_body = json.loads(response.read().decode("utf-8"))
                return res_body.get("message", {}).get("content", "").strip()
        except urllib.error.URLError as e:
            logger.error("Failed to connect to Ollama Vision at %s: %s", api_url, e)
            raise ConnectionError(f"Cannot reach Ollama at {api_url}: {e}") from e

    # 2. OpenAI / Gemini / DeepSeek compatible vision endpoint
    api_url = f"{selected_base_url}/chat/completions"
    data_url = f"data:{mime_type};base64,{b64_img}"
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]
    payload = {
        "model": selected_model,
        "messages": messages,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(api_url, data=req_data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_body = json.loads(response.read().decode("utf-8"))
            return res_body["choices"][0]["message"]["content"].strip()
    except urllib.error.URLError as e:
        logger.error("Failed to connect to Vision LLM endpoint at %s: %s", api_url, e)
        raise ConnectionError(f"Cannot reach LLM endpoint at {api_url}: {e}") from e
