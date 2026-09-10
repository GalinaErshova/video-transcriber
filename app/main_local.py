"""AI-транскрибатор видео — локальный Whisper (faster-whisper)."""
import re
import uuid
import threading
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from urllib.parse import quote

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AI-транскрибатор видео (локальный Whisper)")

# In-memory task store (enough for a single-user tool)
_tasks: dict[str, dict] = {}
_lock = threading.Lock()

# ---------- Whisper model (lazy load) ----------
_model = None
_model_lock = threading.Lock()


def _get_model():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            # small model: good quality, ~1 GB VRAM, runs on CPU too
            _model = WhisperModel("small", device="cpu", compute_type="int8")
        return _model


def _transcribe_file(file_path: str, task_id: str) -> str:
    """Run faster-whisper on a file and return the transcript text."""
    model = _get_model()
    segments, info = model.transcribe(file_path, beam_size=5, language=None)
    parts = []
    for seg in segments:
        parts.append(seg.text.strip())
    return "\n".join(parts)


def _run_task(task_id: str, file_path: str, original_filename: str):
    """Background worker for one transcription task."""
    with _lock:
        _tasks[task_id]["status"] = "STARTED"
    try:
        transcript = _transcribe_file(file_path, task_id)
        with _lock:
            _tasks[task_id].update(
                status="SUCCESS",
                result={"filename": original_filename, "transcript": transcript},
            )
    except Exception as exc:
        with _lock:
            _tasks[task_id].update(status="FAILURE", error=str(exc))


# ---------- HTML UI ----------
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
    .backend-note { background: #ecfdf3; border: 1px solid #a6f4c5; border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; font-size: 14px; color: #067647; }
  </style>
</head>
<body>
  <h1>AI-транскрибатор видео</h1>
  <div class="backend-note">🎤 Локальный Whisper (faster-whisper, модель small) — без API-ключей, всё на вашем компьютере</div>
  <p class="muted">Загрузите один или несколько видео/аудиофайлов.</p>
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
  row.innerHTML = '<td class="filename"></td><td class="status">PENDING</td><td class="result"></td><td class="action"></td>';
  row.dataset.taskId = task.task_id;
  row.querySelector('.filename').textContent = task.filename;
  document.getElementById('tasks').prepend(row);
  rows.set(task.task_id, row);
}

async function refresh(taskId) {
  const row = rows.get(taskId);
  if (!row) return;
  const data = await fetch('/status/' + encodeURIComponent(taskId)).then(r => r.json());
  row.querySelector('.status').textContent = data.status;
  if (data.status === 'SUCCESS' && data.result) {
    row.querySelector('.result').textContent = data.result.transcript || '';
    const link = document.createElement('a');
    link.className = 'download';
    link.href = '/download/' + encodeURIComponent(taskId);
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
  setTimeout(() => refresh(taskId), 2000);
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
  message.textContent = data.tasks.length + ' задач(и) поставлено в очередь';
  submit.disabled = false;
  form.reset();
});
</script>
</body>
</html>"""


# ---------- API ----------
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

        task_id = uuid.uuid4().hex
        with _lock:
            _tasks[task_id] = {
                "status": "PENDING",
                "result": None,
                "error": None,
            }

        t = threading.Thread(
            target=_run_task,
            args=(task_id, str(destination), original_filename),
            daemon=True,
        )
        t.start()
        tasks.append({"task_id": task_id, "filename": original_filename})
    return {"tasks": tasks}


@app.get("/status/{task_id}")
def status(task_id: str) -> dict:
    with _lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return {"task_id": task_id, "status": task["status"], "result": task["result"], "error": task.get("error")}


@app.get("/download/{task_id}")
def download_transcript(task_id: str) -> Response:
    with _lock:
        task = _tasks.get(task_id)
    if task is None or task["status"] != "SUCCESS" or not isinstance(task.get("result"), dict):
        raise HTTPException(status_code=404, detail="Транскрибация ещё не готова или не найдена")

    transcript = task["result"].get("transcript", "")
    original_filename = task["result"].get("filename", "transcript")
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
