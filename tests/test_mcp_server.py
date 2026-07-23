from unittest.mock import MagicMock, patch


class TestListTools:
    def test_tools_endpoint_returns_list(self, mcp_client):
        resp = mcp_client.get("/tools")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "tools" in data
        assert len(data["tools"]) > 0

    def test_transcribe_tool_present(self, mcp_client):
        resp = mcp_client.get("/tools")
        tools = resp.get_json()["tools"]
        names = [t["name"] for t in tools]
        assert "transcribe_video" in names

    def test_tool_has_schema(self, mcp_client):
        resp = mcp_client.get("/tools")
        tool = resp.get_json()["tools"][0]
        assert "inputSchema" in tool
        assert "properties" in tool["inputSchema"]
        assert "file_path" in tool["inputSchema"]["properties"]


class TestCallTool:
    def test_call_no_file_path(self, mcp_client):
        resp = mcp_client.post("/call", json={})
        assert resp.status_code == 400
        assert "file_path" in resp.get_json()["error"]

    def test_call_file_not_found(self, mcp_client):
        resp = mcp_client.post("/call", json={"file_path": "/nonexistent/file.mp4"})
        assert resp.status_code == 404
        assert "не найден" in resp.get_json()["error"]

    @patch("mcp_server.run_transcription")
    def test_call_creates_job(self, mock_transcribe, mcp_client, tmp_path):
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio")
        resp = mcp_client.post("/call", json={"file_path": str(test_file)})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "job_id" in data

    @patch("mcp_server.run_transcription")
    def test_call_default_language(self, mock_transcribe, mcp_client, tmp_path):
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio")
        resp = mcp_client.post("/call", json={"file_path": str(test_file)})
        assert resp.status_code == 200


class TestGetJob:
    def test_get_nonexistent_job(self, mcp_client):
        resp = mcp_client.get("/job/nonexistent")
        assert resp.status_code == 404

    def test_get_existing_job(self, mcp_client):
        from mcp_server import jobs, jobs_lock

        job_id = "test-job-123"
        with jobs_lock:
            jobs[job_id] = {
                "status": "done",
                "progress": 1.0,
                "phase": "done",
                "result": "| Time | Text |\n|------|------|\n| 0:00 | Hello |",
                "file_path": None,
                "cancelled": False,
            }
        resp = mcp_client.get(f"/job/{job_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "done"
        assert data["progress"] == 1.0
        assert "Hello" in data["result"]


class TestCancelJob:
    def test_cancel_nonexistent_job(self, mcp_client):
        resp = mcp_client.post("/cancel/nonexistent")
        assert resp.status_code == 404

    def test_cancel_running_job(self, mcp_client, tmp_path):
        from mcp_server import jobs, jobs_lock

        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio")

        job_id = "test-cancel-job"
        with jobs_lock:
            jobs[job_id] = {
                "status": "running",
                "progress": 0.5,
                "phase": "transcribing",
                "result": None,
                "file_path": str(test_file),
                "cancelled": False,
            }

        resp = mcp_client.post(f"/cancel/{job_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

        from mcp_server import jobs as j
        from mcp_server import jobs_lock as jl

        with jl:
            assert j[job_id]["cancelled"] is True
            assert j[job_id]["status"] == "cancelled"

    def test_cancel_already_done_job(self, mcp_client):
        from mcp_server import jobs, jobs_lock

        job_id = "test-done-cancel"
        with jobs_lock:
            jobs[job_id] = {
                "status": "done",
                "progress": 1.0,
                "phase": "done",
                "result": "finished",
                "file_path": None,
                "cancelled": False,
            }

        resp = mcp_client.post(f"/cancel/{job_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "done"


class TestGetModel:
    def test_model_lazy_loaded(self):
        import mcp_server

        assert mcp_server.model is None

    def test_model_loaded_once(self):
        import mcp_server

        original_model = mcp_server.model
        mcp_server.model = None
        mock_whisper_cls = MagicMock()
        mock_whisper_cls.return_value = MagicMock()

        with patch.dict("sys.modules", {"faster_whisper": MagicMock(WhisperModel=mock_whisper_cls)}):
            m1 = mcp_server.get_model()
            m2 = mcp_server.get_model()
            assert m1 is m2

        mcp_server.model = original_model
