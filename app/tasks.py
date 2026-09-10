import os
from pathlib import Path
from typing import Any

from .celery_app import celery_app


@celery_app.task(bind=True, name="transcribe_video")
def transcribe_video(self, file_path: str, original_filename: str) -> dict[str, Any]:
    """Transcribe one uploaded media file and return a JSON-serializable result."""
    backend = os.getenv("TRANSCRIPTION_BACKEND", "openai").lower()
    if backend != "openai":
        raise RuntimeError(
            "Поддерживается backend=openai. Установите TRANSCRIPTION_BACKEND=openai."
        )

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("sk-proj-your-key"):
        raise RuntimeError("OPENAI_API_KEY не настроен в файле .env")

    from openai import OpenAI

    self.update_state(state="STARTED", meta={"filename": original_filename})
    client = OpenAI(api_key=api_key)
    with Path(file_path).open("rb") as media_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=media_file,
            response_format="text",
        )

    transcript = response if isinstance(response, str) else response.text
    return {
        "filename": original_filename,
        "transcript": transcript,
        "status": "done",
    }
