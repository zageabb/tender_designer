from __future__ import annotations

import json
import re

import requests


class OllamaClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def generate_json(self, model: str, prompt: str) -> tuple[dict | None, str, str | None]:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=500)
        response.raise_for_status()
        raw_response = response.json().get("response", "")
        candidate = _extract_json_candidate(raw_response)
        try:
            return json.loads(candidate), raw_response, None
        except json.JSONDecodeError as exc:
            return None, raw_response, str(exc)

    def generate_text(self, model: str, prompt: str) -> str:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=500)
        response.raise_for_status()
        return response.json().get("response", "").strip()

    def chat_text(
        self,
        model: str,
        messages: list[dict],
        *,
        system_prompt: str = "",
        temperature: float = 0.2,
        num_ctx: int | None = None,
    ) -> str:
        bounded: list[dict] = []
        if system_prompt.strip():
            bounded.append({"role": "system", "content": system_prompt.strip()[:40000]})
        for message in messages[-24:]:
            role = str(message.get("role") or "user")
            if role not in {"user", "assistant", "system"}:
                continue
            content = str(message.get("content") or message.get("message_text") or "").strip()
            if content:
                bounded.append({"role": role, "content": content[:30000]})
        payload = {
            "model": model,
            "messages": bounded,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if num_ctx:
            payload["options"]["num_ctx"] = int(num_ctx)
        response = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=500)
        response.raise_for_status()
        message = response.json().get("message") or {}
        return str(message.get("content") or "").strip()

    def embed_texts(self, model: str, texts: list[str]) -> list[list[float]]:
        """Return Ollama embeddings for a batch of texts.

        The research code treats embeddings as an optional quality improvement, so
        callers are expected to fall back gracefully when the configured model is
        unavailable on the local Ollama server.
        """
        clean_texts = [str(text or "")[:12000] for text in texts]
        if not clean_texts:
            return []
        payload = {"model": model, "input": clean_texts}
        response = requests.post(f"{self.base_url}/api/embed", json=payload, timeout=120)
        response.raise_for_status()
        rows = response.json().get("embeddings") or []
        if not isinstance(rows, list) or len(rows) != len(clean_texts):
            raise ValueError("Ollama returned an unexpected embedding response.")
        return [
            [float(value) for value in row]
            for row in rows
            if isinstance(row, list)
        ]

    def list_models(self) -> list[str]:
        response = requests.get(f"{self.base_url}/api/tags", timeout=10)
        response.raise_for_status()
        return [model.get("name", "") for model in response.json().get("models", [])]


def _extract_json_candidate(raw_response: str) -> str:
    stripped = raw_response.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    first_object = stripped.find("{")
    first_array = stripped.find("[")
    indices = [index for index in (first_object, first_array) if index != -1]
    if indices:
        return stripped[min(indices) :]
    return stripped
