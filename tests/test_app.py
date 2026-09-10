from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_home_page_contains_download_ui():
    response = client.get("/")
    assert response.status_code == 200
    assert "Скачать .txt" in response.text
    assert "/download/" in response.text


def test_download_returns_completed_transcript():
    completed = Mock()
    completed.successful.return_value = True
    completed.result = {"filename": "лекция.mp4", "transcript": "Добрый день"}
    with patch("app.main.AsyncResult", return_value=completed):
        response = client.get("/download/task-1")

    assert response.status_code == 200
    assert response.text == "Добрый день"
    assert response.headers["content-type"].startswith("text/plain")
    assert "attachment" in response.headers["content-disposition"]
    assert "filename*=UTF-8''%D0%BB%D0%B5%D0%BA%D1%86%D0%B8%D1%8F.txt" in response.headers[
        "content-disposition"
    ]


def test_download_is_unavailable_before_success():
    pending = Mock()
    pending.successful.return_value = False
    pending.result = None
    with patch("app.main.AsyncResult", return_value=pending):
        response = client.get("/download/task-2")

    assert response.status_code == 404


def test_transcribe_queues_multiple_files():
    queued = [Mock(id="task-1"), Mock(id="task-2")]
    with patch("app.main.transcribe_video.delay", side_effect=queued):
        response = client.post(
            "/transcribe",
            files=[
                ("files", ("one.mp3", b"audio-one", "audio/mpeg")),
                ("files", ("two.mp4", b"video-two", "video/mp4")),
            ],
        )

    assert response.status_code == 200
    assert response.json()["tasks"] == [
        {"task_id": "task-1", "filename": "one.mp3"},
        {"task_id": "task-2", "filename": "two.mp4"},
    ]
