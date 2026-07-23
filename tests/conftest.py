import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _env_isolation(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-12345")
    monkeypatch.setenv("PORT", "0")
    monkeypatch.setenv("MCP_PORT", "0")
    monkeypatch.setenv("VOSK_PORT", "0")


@pytest.fixture()
def client():
    from server import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def mcp_client():
    from mcp_server import app as mcp_app

    mcp_app.config["TESTING"] = True
    with mcp_app.test_client() as c:
        yield c


@pytest.fixture()
def tmp_upload(tmp_path):
    from server import UPLOAD_DIR

    original = UPLOAD_DIR
    import server

    server.UPLOAD_DIR = str(tmp_path)
    yield tmp_path
    server.UPLOAD_DIR = original
