"""Vertex AI Gemini vision provider pour l'extraction JSON de tickets.

Auth via ADC (pas de clé JSON — org policy `iam.disableServiceAccountKeyCreation`).
Le SA Cloud Run du worker doit avoir `roles/aiplatform.user`.

Interface volontairement identique à ``GroqProvider`` (``analyze(path, prompt)
-> str``) pour rester interchangeable dans ``ocr.run_ocr``.
"""

from __future__ import annotations

from pathlib import Path


class GeminiProvider:
    def __init__(self, model: str, project: str | None, location: str) -> None:
        self._model = model
        self._project = project or None
        self._location = location
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - dépendance de build
            raise ImportError(
                "GeminiProvider requires the 'google-genai' package."
            ) from exc
        self._client = genai.Client(
            vertexai=True, project=self._project, location=self._location
        )
        return self._client

    def analyze(self, image_path: str, prompt: str) -> str:
        from google.genai import types

        path = Path(image_path)
        raw = path.read_bytes()
        mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"

        client = self._get_client()
        response = client.models.generate_content(  # type: ignore[attr-defined]
            model=self._model,
            contents=[
                types.Part.from_bytes(data=raw, mime_type=mime),
                prompt,
            ],
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        text = getattr(response, "text", None)
        if not text or not str(text).strip():
            raise RuntimeError("Gemini returned an empty response.")
        return str(text).strip()
