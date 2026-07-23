import io
import json
from unittest.mock import MagicMock, patch


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "ok" in data
        assert "mcp" in data
        assert "deepseek" in data

    def test_health_deepseek_ok_with_key(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["deepseek"] is True

    @patch("server.httpx")
    def test_health_mcp_ok_when_tools_responds(self, mock_httpx, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx.get.return_value = mock_resp
        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["mcp"] is True

    @patch("server.httpx")
    def test_health_mcp_down(self, mock_httpx, client):
        mock_httpx.get.side_effect = Exception("Connection refused")
        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["mcp"] is False


class TestStatsEndpoint:
    @patch("server.subprocess")
    @patch("server.psutil")
    def test_stats_returns_metrics(self, mock_psutil, mock_subprocess, client):
        mock_psutil.cpu_percent.return_value = 45.2
        mock_mem = MagicMock()
        mock_mem.used = 8 * 1024 ** 3
        mock_mem.total = 16 * 1024 ** 3
        mock_mem.percent = 50.0
        mock_psutil.virtual_memory.return_value = mock_mem
        mock_subprocess.check_output.return_value = b"4096, 8192\n"

        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "cpu" in data
        assert "ram_used" in data
        assert "ram_total" in data
        assert "ram_percent" in data

    @patch("server.subprocess")
    @patch("server.psutil")
    def test_stats_gpu_null_when_nvidia_smi_fails(self, mock_psutil, mock_subprocess, client):
        mock_psutil.cpu_percent.return_value = 10.0
        mock_mem = MagicMock()
        mock_mem.used = 4 * 1024 ** 3
        mock_mem.total = 16 * 1024 ** 3
        mock_mem.percent = 25.0
        mock_psutil.virtual_memory.return_value = mock_mem
        mock_subprocess.check_output.side_effect = FileNotFoundError("nvidia-smi not found")

        resp = client.get("/api/stats")
        data = resp.get_json()
        assert data["gpu_used"] is None
        assert data["gpu_total"] is None


class TestUploadEndpoint:
    def test_upload_no_file(self, client):
        resp = client.post("/api/upload")
        assert resp.status_code == 400
        assert "Файл не предоставлен" in resp.get_json()["error"]

    def test_upload_empty_filename(self, client):
        data = {"file": (io.BytesIO(b"content"), "")}
        resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_upload_disallowed_extension(self, client):
        data = {"file": (io.BytesIO(b"content"), "test.exe")}
        resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert "не поддерживается" in resp.get_json()["error"]

    def test_upload_allowed_extension(self, client):
        data = {"file": (io.BytesIO(b"fake audio data"), "test.mp3")}
        resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 200
        result = resp.get_json()
        assert "file_id" in result
        assert "path" in result
        assert "name" in result
        assert "size" in result

    def test_upload_oversized_file(self, client):
        big_data = b"x" * (500 * 1024 * 1024 + 1)
        data = {"file": (io.BytesIO(big_data), "big.mp4")}
        resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert "большой" in resp.get_json()["error"]

    def test_upload_sanitize_filename(self, client):
        data = {"file": (io.BytesIO(b"data"), "my<file>.mp3")}
        resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
        result = resp.get_json()
        assert "<" not in result["name"]

    def test_upload_returns_unique_id(self, client):
        data1 = {"file": (io.BytesIO(b"data1"), "file1.mp3")}
        data2 = {"file": (io.BytesIO(b"data2"), "file2.mp3")}
        r1 = client.post("/api/upload", data=data1, content_type="multipart/form-data")
        r2 = client.post("/api/upload", data=data2, content_type="multipart/form-data")
        assert r1.get_json()["file_id"] != r2.get_json()["file_id"]


class TestChatEndpoint:
    def test_chat_no_message(self, client):
        resp = client.post("/api/chat", json={})
        assert resp.status_code == 400

    @patch("server._deepseek")
    def test_chat_empty_message_sends_to_deepseek(self, mock_deepseek, client):
        mock_deepseek.return_value = {"content": "reply"}
        resp = client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 200

    def test_chat_missing_file(self, client):
        resp = client.post("/api/chat", json={
            "message": "test",
            "file_path": "/nonexistent/file.mp4",
        })
        assert resp.status_code == 400
        assert "не найден" in resp.get_json()["error"]

    @patch("server._deepseek")
    def test_chat_returns_reply(self, mock_deepseek, client):
        mock_deepseek.return_value = {"content": "Привет! Чем могу помочь?"}
        resp = client.post("/api/chat", json={"message": "Привет"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "message" in data
        assert data["message"] == "Привет! Чем могу помочь?"

    @patch("server._deepseek")
    def test_chat_deepseek_error_returns_502(self, mock_deepseek, client):
        import httpx
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_deepseek.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock_resp
        )
        resp = client.post("/api/chat", json={"message": "test"})
        assert resp.status_code == 502

    @patch("server._deepseek")
    def test_chat_creates_conversation(self, mock_deepseek, client):
        mock_deepseek.return_value = {"content": "reply"}
        resp = client.post("/api/chat", json={"message": "hello"})
        data = resp.get_json()
        assert "conversation_id" in data

    @patch("server._deepseek")
    def test_chat_tool_call_summarize(self, mock_deepseek, client):
        mock_deepseek.side_effect = [
            {
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "summarize_text",
                        "arguments": json.dumps({"text": "long text here", "language": "en"}),
                    },
                }],
            },
            {"content": "Summary of the text"},
        ]
        resp = client.post("/api/chat", json={"message": "summarize this"})
        assert resp.status_code == 200


class TestSummarizeEndpoint:
    def test_summarize_no_text(self, client):
        resp = client.post("/api/summarize", json={})
        assert resp.status_code == 400

    def test_summarize_empty_text(self, client):
        resp = client.post("/api/summarize", json={"text": "  "})
        assert resp.status_code == 400

    @patch("server._deepseek")
    def test_summarize_returns_summary(self, mock_deepseek, client):
        mock_deepseek.return_value = {"content": "This is a summary"}
        resp = client.post("/api/summarize", json={"text": "Some long text"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["summary"] == "This is a summary"

    @patch("server._deepseek")
    def test_summarize_deepseek_error(self, mock_deepseek, client):
        import httpx
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_deepseek.side_effect = httpx.HTTPStatusError(
            "rate limit", request=MagicMock(), response=mock_resp
        )
        resp = client.post("/api/summarize", json={"text": "text"})
        assert resp.status_code == 502


class TestCancelEndpoint:
    def test_cancel_nonexistent_job(self, client):
        resp = client.post("/api/cancel/nonexistent-id")
        assert resp.status_code == 404

    def test_cancel_already_done(self, client):
        import server

        job_id = "test-done-job"
        with server.stream_lock:
            server.stream_results[job_id] = {
                "status": "done",
                "progress": 1.0,
                "phase": "done",
                "message": "result",
                "error": None,
                "mcp_job_id": None,
                "file_path": None,
                "conversation_id": None,
                "start_time": 0,
                "cancelled": False,
            }
        resp = client.post(f"/api/cancel/{job_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "done"


class TestStreamEndpoint:
    def test_stream_nonexistent_job(self, client):
        resp = client.get("/api/stream/nonexistent-id")
        assert resp.status_code == 200
        assert b"error" in resp.data


class TestStaticRoutes:
    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_css_returns_css(self, client):
        resp = client.get("/css/style.css")
        assert resp.status_code == 200

    def test_js_returns_js(self, client):
        resp = client.get("/js/app.js")
        assert resp.status_code == 200
