import re
import uuid
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from celery.result import AsyncResult
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

from .celery_app import celery_app
from .tasks import transcribe_video


UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AI-транскрибатор видео")


def _text_filename(original_filename: str) -> str:
    stem = Path(original_filename or "transcript").stem
    safe_stem = re.sub(r"[^\w\-. ]+", "_", stem, flags=re.UNICODE).strip(" .")
    return f"{safe_stem or 'transcript'}.txt"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI-транскрибатор видео</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, sans-serif; }
    body { max-width: 980px; margin: 40px auto; padding: 0 20px; color: #172033; }
    h1 { margin-bottom: 8px; }
    .muted { color: #667085; }
    form { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 20px; background: #f3f6fb; border-radius: 12px; }
    button, .download { border: 0; border-radius: 8px; padding: 10px 14px; background: #155eef; color: white; cursor: pointer; text-decoration: none; display: inline-block; }
    button:disabled { opacity: .6; cursor: wait; }
    table { width: 100%; border-collapse: collapse; margin-top: 28px; }
    th, td { text-align: left; vertical-align: top; padding: 12px 10px; border-bottom: 1px solid #e4e7ec; }
    th { color: #475467; font-size: 14px; }
    .status { font-weight: 650; }
    .result { white-space: pre-wrap; min-width: 260px; }
    .error { color: #b42318; }
  </style>
</head>
<body>
  <h1>AI-транскрибатор видео</h1>
  <p class="muted">Загрузите один или несколько файлов до 25 МБ каждый.</p>
  <form id="upload-form">
    <input id="files" name="files" type="file" accept="video/*,audio/*" multiple required>
    <button id="submit" type="submit">Транскрибировать</button>
    <span id="message" class="muted"></span>
  </form>
  <table>
    <thead><tr><th>Файл</th><th>Статус</th><th>Результат</th><th></th></tr></thead>
    <tbody id="tasks"></tbody>
  </table>
<script>
const form = document.getElementById('upload-form');
const filesInput = document.getElementById('files');
const submit = document.getElementById('submit');
const message = document.getElementById('message');
const rows = new Map();

function makeRow(task) {
  const row = document.createElement('tr');
  row.innerHTML = `<td class="filename"></td><td class="status">PENDING</td><td class="result"></td><td class="action"></td>`;
  row.dataset.taskId = task.task_id;
  row.querySelector('.filename').textContent = task.filename;
  document.getElementById('tasks').prepend(row);
  rows.set(task.task_id, row);
}

async function refresh(taskId) {
  const row = rows.get(taskId);
  if (!row) return;
  const data = await fetch(`/status/${encodeURIComponent(taskId)}`).then(r => r.json());
  row.querySelector('.status').textContent = data.status;
  if (data.status === 'SUCCESS' && data.result) {
    row.querySelector('.result').textContent = data.result.transcript || '';
    const link = document.createElement('a');
    link.className = 'download';
    link.href = `/download/${encodeURIComponent(taskId)}`;
    link.textContent = 'Скачать .txt';
    link.download = '';
    row.querySelector('.action').replaceChildren(link);
    return;
  }
  if (data.status === 'FAILURE') {
    row.querySelector('.result').textContent = data.error || 'Задача завершилась с ошибкой';
    row.querySelector('.result').classList.add('error');
    return;
  }
  setTimeout(() => refresh(taskId), 1500);
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  submit.disabled = true;
  message.textContent = 'Файлы отправляются…';
  const body = new FormData();
  for (const file of filesInput.files) body.append('files', file);
  const response = await fetch('/transcribe', { method: 'POST', body });
  const data = await response.json();
  if (!response.ok) {
    message.textContent = data.detail || 'Не удалось загрузить файлы';
    submit.disabled = false;
    return;
  }
  data.tasks.forEach(makeRow);
  data.tasks.forEach(task => refresh(task.task_id));
  message.textContent = `${data.tasks.length} задач(и) поставлено в очередь`;
  submit.disabled = false;
  form.reset();
});
</script>
</body>
</html>"""


@app.post("/transcribe")
async def transcribe(
    files: Annotated[list[UploadFile], File(description="Видео или аудиофайлы")],
) -> dict:
    tasks = []
    for uploaded_file in files:
        original_filename = uploaded_file.filename or "audio"
        stored_name = f"{uuid.uuid4().hex}_{Path(original_filename).name}"
        destination = UPLOAD_DIR / stored_name
        with destination.open("wb") as output:
            while chunk := await uploaded_file.read(1024 * 1024):
                output.write(chunk)
        task = transcribe_video.delay(str(destination), original_filename)
        tasks.append({"task_id": task.id, "filename": original_filename})
    return {"tasks": tasks}


@app.get("/status/{task_id}")
def status(task_id: str) -> dict:
    result = AsyncResult(task_id, app=celery_app)
    payload = {"task_id": task_id, "status": result.status, "result": None}
    if result.successful():
        payload["result"] = result.result
    elif result.failed():
        payload["error"] = str(result.result)
    return payload


@app.get("/download/{task_id}")
def download_transcript(task_id: str) -> Response:
    """Return a completed transcript as a downloadable UTF-8 text file."""
    result = AsyncResult(task_id, app=celery_app)
    if not result.successful() or not isinstance(result.result, dict):
        raise HTTPException(status_code=404, detail="Транскрибация ещё не готова или не найдена")

    transcript = result.result.get("transcript")
    original_filename = result.result.get("filename", "transcript")
    if not isinstance(transcript, str):
        raise HTTPException(status_code=404, detail="Текст транскрибации не найден")

    filename = _text_filename(str(original_filename))
    ascii_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or "transcript.txt"
    disposition = (
        f'attachment; filename="{ascii_filename}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return Response(
        content=transcript,
        media_type="text/plain",
        headers={"Content-Disposition": disposition},
    )
