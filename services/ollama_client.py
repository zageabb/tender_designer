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
