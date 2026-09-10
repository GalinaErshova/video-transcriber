# AI-транскрибатор видео

Учебный проект по гайду: FastAPI принимает несколько видео/аудиофайлов, ставит их в очередь Celery через Redis, а Flower показывает состояние воркеров и задач.

## Запуск

1. Установите и запустите Docker Desktop.
2. В `.env` замените `OPENAI_API_KEY` на ваш ключ OpenAI. Ключ не добавляйте в Git.
3. В корне проекта выполните:

```bash
docker compose up --build
```

Откройте:

- http://localhost:8000 — форма загрузки;
- http://localhost:8000/docs — Swagger UI;
- http://localhost:5555 — Flower.

Для трёх параллельных воркеров:

```bash
docker compose down
docker compose up --build --scale worker=3
```

Загрузите три коротких файла одновременно и проверьте переход `PENDING → STARTED → SUCCESS` в интерфейсе и Flower.

## Скачивание транскрибации

После успешной задачи рядом с текстом появляется кнопка `Скачать .txt`. Она вызывает `GET /download/{task_id}` и возвращает UTF-8 текстовый файл с именем на основе исходного файла. До завершения задачи эндпоинт возвращает `404`.

## Проверка без Docker

Для локальных unit-тестов:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest -q
```

Тесты проверяют HTML с кнопкой скачивания, скачивание готового результата, ответ `404` для незавершённой задачи и постановку нескольких файлов в очередь.

## Подробная настройка Windows

Требуется Docker Desktop в режиме Linux containers с WSL2-бэкендом. Проверка установки:

```powershell
docker desktop start
docker desktop status
docker version
docker compose version
```

Если WSL2 не установлен, откройте PowerShell от имени администратора и выполните:

```powershell
wsl --install --no-distribution
```

Перезагрузите Windows, снова запустите Docker Desktop и повторите проверку. Команда `docker desktop` без подкоманды только выводит справку; для запуска используется `docker desktop start`.

## Настройка окружения

Создайте локальный файл настроек из шаблона:

```powershell
Copy-Item .env.example .env
notepad .env
```

Заполните `.env`:

```dotenv
OPENAI_API_KEY=sk-proj-ваш-ключ
TRANSCRIPTION_BACKEND=openai
```

Файл `.env` игнорируется Git. Не добавляйте API-ключ в исходники, README или сообщения коммитов.

## Проверка результата

После запуска откройте:

- `http://localhost:8000` — загрузка файлов и статусы;
- `http://localhost:8000/docs` — Swagger UI;
- `http://localhost:5555` — Flower.

Загрузите три коротких файла одновременно. Для каждой задачи ожидается переход `PENDING → STARTED → SUCCESS`. При `SUCCESS` рядом с текстом появится кнопка «Скачать .txt».

## API

- `POST /transcribe` — загружает один или несколько multipart-файлов и возвращает `task_id`;
- `GET /status/{task_id}` — возвращает статус и результат готовой задачи;
- `GET /download/{task_id}` — отдаёт готовый текст как UTF-8-файл `.txt`; до завершения возвращает `404`.

## Команды диагностики

```powershell
docker compose ps
docker compose logs worker
docker compose logs web
docker compose logs redis
docker compose logs -f worker
docker compose restart flower
```

Частые причины ошибок:

- `PENDING` — worker не запущен или не подключён к Redis;
- `AuthenticationError` — неверный или отсутствующий `OPENAI_API_KEY`;
- `Maximum content size limit exceeded` — файл больше лимита Whisper API в 25 МБ;
- `Port 8000 is already allocated` — порт занят другим процессом;
- `dockerDesktopLinuxEngine ... pipe ... not found` — Docker Desktop не запущен или WSL2 не настроен.

## Структура проекта

```text
app/
  celery_app.py   # Celery и Redis broker/backend
  tasks.py        # фоновая транскрибация через Whisper API
  main.py         # FastAPI, HTML-интерфейс и download endpoint
tests/test_app.py # unit-тесты
Dockerfile
docker-compose.yml
requirements.txt
.env.example
```
