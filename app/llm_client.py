import json
import os
from typing import Any

import httpx

from app.errors import AppError

DEFAULT_API_BASE = "https://api.studio.nebius.com/v1"
FALLBACK_API_BASE = "https://api.tokenfactory.nebius.com/v1"
DEFAULT_MODEL = "meta-llama/Llama-3.3-70B-Instruct"
MODEL_PREFERENCES = [
    "meta-llama/Llama-3.3-70B-Instruct",
    "meta-llama/Meta-Llama-3.1-70B-Instruct",
    "meta-llama/Meta-Llama-3.1-8B-Instruct",
]


def _normalize_base_url(url: str) -> str:
    return url.rstrip("/")


async def _list_models(client: httpx.AsyncClient, api_key: str, api_base: str) -> list[str]:
    response = await client.get(
        f"{api_base}/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    if response.status_code >= 400:
        return []

    try:
        payload = response.json()
    except json.JSONDecodeError:
        return []

    data = payload.get("data", [])
    if not isinstance(data, list):
        return []

    models: list[str] = []
    for item in data:
        if isinstance(item, dict):
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id.strip():
                models.append(model_id)
    return models


def _pick_model(available_models: list[str]) -> str:
    for preferred in MODEL_PREFERENCES:
        if preferred in available_models:
            return preferred
    return available_models[0] if available_models else DEFAULT_MODEL


async def call_llm(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    api_key = os.getenv("NEBIUS_API_KEY")
    if not api_key:
        raise AppError(500, "NEBIUS_API_KEY environment variable is not set")

    configured_base = _normalize_base_url(os.getenv("NEBIUS_API_BASE", DEFAULT_API_BASE))
    api_bases = [configured_base]
    if configured_base != FALLBACK_API_BASE:
        api_bases.append(FALLBACK_API_BASE)

    timeout = httpx.Timeout(60.0, connect=10.0)
    last_error: Exception | None = None

    for api_base in api_bases:
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    selected_model = os.getenv("NEBIUS_MODEL", "").strip()
                    if not selected_model:
                        available_models = await _list_models(client, api_key, api_base)
                        selected_model = _pick_model(available_models)

                    payload = {
                        "model": selected_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 1200,
                        "response_format": {"type": "json_object"},
                    }

                    response = await client.post(
                        f"{api_base}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )

                if response.status_code >= 400:
                    details = ""
                    try:
                        err = response.json()
                        details = err.get("error", {}).get("message") or err.get("message") or ""
                    except json.JSONDecodeError:
                        details = ""
                    message = f"LLM provider error: HTTP {response.status_code}"
                    if details:
                        message = f"{message} ({details})"
                    raise AppError(502, message)

                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                parsed = json.loads(content)
                if not isinstance(parsed.get("summary"), str):
                    raise AppError(502, "LLM returned invalid 'summary' field")
                if not isinstance(parsed.get("technologies"), list):
                    raise AppError(502, "LLM returned invalid 'technologies' field")
                if not isinstance(parsed.get("structure"), str):
                    raise AppError(502, "LLM returned invalid 'structure' field")

                parsed["technologies"] = [str(item) for item in parsed["technologies"] if str(item).strip()]
                return parsed

            except AppError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt == 1:
                    break
            except json.JSONDecodeError as exc:
                raise AppError(502, "LLM returned invalid JSON") from exc
            except KeyError as exc:
                raise AppError(502, "LLM returned unexpected response structure") from exc

    if isinstance(last_error, AppError):
        raise last_error
    if isinstance(last_error, (httpx.TimeoutException, httpx.NetworkError)):
        raise AppError(504, "LLM request timed out or failed due to network error")

    raise AppError(502, "Failed to generate summary from LLM")
