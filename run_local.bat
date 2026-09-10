@echo off
REM Запуск локального транскрибатора (без Docker, без API-ключей)
cd /d "%~dp0"
.venv\Scripts\python.exe -m uvicorn app.main_local:app --host 0.0.0.0 --port 8000 --reload
