# CLAUDE.md — Project Rules

## Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ (backend), vanilla JS ES5 (frontend) |
| Web framework | Flask 3.x + Flask-CORS |
| AI/ML | faster-whisper (Whisper CTranslate2), DeepSeek Chat API |
| HTTP client | httpx (async-ready, used sync) |
| System monitoring | psutil, nvidia-smi subprocess |
| Config | python-dotenv (.env) |
| Real-time | Server-Sent Events (SSE) |
| Frontend build | None (no bundler, no framework) |

## Architecture

```
Browser (public/)  ──HTTP──>  server.py (:3000)  ──HTTP──>  mcp_server.py (:3001)
                              │                              │
                              ├─ REST API endpoints          ├─ Whisper model (lazy-loaded)
                              ├─ DeepSeek chat + tools       ├─ Job queue (in-memory)
                              ├─ SSE streaming               ├─ Transcription worker
                              └─ Static file serving         └─ MCP-like HTTP protocol
```

- **server.py** — main entry point, starts mcp_server as subprocess, handles all client communication
- **mcp_server.py** — internal worker, manages Whisper model and transcription jobs, NOT exposed to internet
- Communication between servers: plain HTTP (localhost only)

## Folder Structure

```
transcriber/
├── server.py              # Main Flask server (API + static)
├── mcp_server.py          # Internal transcription worker
├── public/                # Frontend (served as static)
│   ├── index.html         # Single-page app
│   ├── css/style.css      # All styles (dark theme)
│   └── js/app.js          # All frontend logic (single IIFE)
├── uploads/               # Temp file storage (gitignored, auto-cleaned)
├── .env                   # Secrets (gitignored)
├── .env.example           # Template
├── requirements.txt       # Python dependencies
├── pyproject.toml         # Ruff + mypy config
├── package.json           # npm scripts only (start/mcp)
└── CLAUDE.md              # This file
```

## Naming Conventions

### Python
- **Files**: `snake_case.py` (e.g., `mcp_server.py`)
- **Functions**: `snake_case` (e.g., `run_transcription_stream`)
- **Private helpers**: `_prefix` (e.g., `_deepseek()`, `_delete_file()`, `_elapsed()`)
- **Constants**: `UPPER_SNAKE` (e.g., `MCP_URL`, `MAX_FILE_SIZE`, `ALLOWED_EXTENSIONS`)
- **Route handlers**: verb-noun or noun (e.g., `upload()`, `chat()`, `health()`, `sse_stream()`)
- **Globals**: lowercase, module-level (e.g., `model`, `jobs`, `conversations`)

### JavaScript
- **Functions**: `camelCase` (e.g., `renderChatList`, `sendMessage`)
- **DOM elements**: `camelCase` + `El` suffix (e.g., `messagesEl`, `inputEl`, `sendBtn`)
- **Event handlers**: `handle` + noun (e.g., `handleFile`)

### Routes
- API endpoints: `/api/<resource>` or `/api/<action>`
- Examples: `/api/health`, `/api/upload`, `/api/chat`, `/api/stream/<id>`, `/api/cancel/<id>`

## Patterns

1. **Two-server architecture** — Main server delegates heavy ML work to MCP worker subprocess
2. **Lazy model loading** — Whisper model loaded on first transcription request, not at startup
3. **Thread-based job queue** — Each transcription runs in a daemon thread, tracked by UUID job_id
4. **SSE for real-time updates** — Progress streamed via `/api/stream/<job_id>` using `text/event-stream`
5. **Tool-calling pattern** — DeepSeek LLM can invoke `transcribe_video` tool, bridging chat and transcription
6. **In-memory state** — Conversations and job results stored in dicts with thread locks (no database)
7. **Graceful cleanup** — atexit + signal handlers terminate MCP subprocess on shutdown

## Agent Configuration

### Subagents

Subagents are isolated processes with their own context, system prompt, and environment. Use them for parallel or sequential task execution.

| Subagent | Purpose | Trigger |
|----------|---------|---------|
| `transcription-worker` | Runs Whisper model on audio/video files | POST `/api/chat` with file |
| `summarizer` | Generates text summaries via DeepSeek | POST `/api/summarize` |
| `health-checker` | Monitors MCP server + DeepSeek availability | GET `/api/health` |

**Rules for subagents:**
- One subagent = one mission (single responsibility)
- Pass artifacts between subagents, not shared state
- Max 5 concurrent subagents (system limit)
- Use independent sessions for isolation

### Skills

Skills are specific abilities invoked by the agent based on context.

| Skill | Description | When to use |
|-------|-------------|-------------|
| `transcribe-audio` | Upload file → MCP worker → SSE progress → result | User uploads video/audio |
| `summarize-text` | Take text → DeepSeek API → summary | User clicks "Саммари" button |
| `chat-with-context` | Maintain conversation history per chat | User sends text message |
| `system-monitoring` | CPU/RAM/GPU stats via psutil/nvidia-smi | Every 3 seconds (frontend poll) |

### Commands

Commands are shortcuts for common operations.

| Command | Action |
|---------|--------|
| `new-chat` | Create fresh conversation context |
| `cancel-job` | Abort active transcription via `/api/cancel/<id>` |
| `check-health` | Verify MCP + DeepSeek connectivity |
| `download-md` | Export transcription/summary as Markdown file |

## Profile & Invariants

### Developer Profile
- **Level**: Junior-mid Python developer
- **Preferences**: Concise responses, minimal comments, Russian UI
- **Style**: Code-first, documentation in CLAUDE.md only

### Invariants (DO NOT CHANGE)
1. **Language**: All UI text, error messages, and status updates in Russian
2. **No database**: In-memory state only (conversations, jobs, stream_results)
3. **No secrets in code**: All config via `.env` + `os.getenv()`
4. **No blocking routes**: Heavy work goes to background threads
5. **Two-server architecture**: Main server never loads ML models directly

## Task States

### Transcription Flow
```
IDLE → UPLOADING → QUEUED → TRANSCRIBING → DONE
                      ↓           ↓
                   CANCELLED    ERROR
```

| State | Description | Next states |
|-------|-------------|-------------|
| `idle` | No active job | `uploading` |
| `uploading` | File being sent to server | `queued`, `error` |
| `queued` | Job created, waiting for worker | `transcribing`, `cancelled` |
| `transcribing` | Whisper processing audio | `done`, `error`, `cancelled` |
| `done` | Transcription complete | `idle` |
| `error` | Failed at any stage | `idle` |
| `cancelled` | User cancelled operation | `idle` |

### Chat Flow
```
NEW → USER_MESSAGE → THINKING → ASSISTANT_RESPONSE → READY
                         ↓
                    TOOL_CALL (transcribe/summarize)
```

### Agent Profiles

Three specialized profiles for different development tasks. Each profile defines system prompt, task flow, constraints, and response format.

| Profile | File | Use when |
|---------|------|----------|
| Bug Fix | `profiles/bug-fix.md` | Bug reports, errors, "не работает", "сломалось" |
| Research | `profiles/research.md` | Codebase questions, "как работает", "объясни" |
| Code Review | `profiles/code-review.md` | Reviews, MR/PR checks, "проверь", "rev" |

**Profile activation:** Add `/load profiles/<name>.md` or prepend "Следуй профилю из profiles/<name>.md" to prompt.

**Profile invariants (shared):**
1. Language — Russian (matching UI)
2. Architecture — two-server (server.py + mcp_server.py)
3. State — in-memory only
4. Secrets — .env + os.getenv() only
5. No blocking I/O in route handlers
6. ruff check + mypy after every change

## Good Code Examples

### Example 1: Lazy model loading with double-checked locking (`mcp_server.py:36-43`)
```python
def get_model():
    global model
    if model is None:
        with model_lock:
            if model is None:
                from faster_whisper import WhisperModel
                model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return model
```
**Why good**: Thread-safe lazy init, import inside function avoids startup cost.

### Example 2: SSE stream endpoint (`server.py:330-364`)
```python
@app.route("/api/stream/<job_id>")
def sse_stream(job_id):
    def generate():
        while True:
            with stream_lock:
                data = stream_results.get(job_id)
            if not data:
                yield f"data: {json.dumps({'status': 'error', 'message': 'Job not found'})}\n\n"
                break
            # ... yield progress events ...
            if data["status"] in ("done", "error", "cancelled"):
                break
            time.sleep(1)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
```
**Why good**: Clean generator pattern, proper SSE headers, handles all terminal states.

### Example 3: File validation with size check (`server.py:302-327`)
```python
@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["filename"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        return jsonify({"error": f"File too large (max {MAX_FILE_SIZE // (1024 * 1024)} MB)"}), 400
    # ... save file ...
    return jsonify({"file_id": file_id, "path": save_path, "name": safe_name, "size": size})
```
**Why good**: Early returns, clear error messages, consistent JSON response format.

### Example 4: Graceful subprocess cleanup (`server.py:34-53`)
```python
def cleanup(signum=None, frame=None):
    global mcp_process, _cleaned
    if _cleaned:
        return
    _cleaned = True
    if mcp_process and mcp_process.poll() is None:
        print("\nStopping MCP server...")
        mcp_process.terminate()
        try:
            mcp_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mcp_process.kill()
        print("Done.")

signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
atexit.register(cleanup)
```
**Why good**: Idempotent cleanup, SIGTERM before SIGKILL, registered via atexit as fallback.

### Example 5: Private helper prefix convention (`server.py:120-136`)
```python
def _deepseek(messages, tools=None):
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "max_tokens": 4096,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    resp = httpx.post(
        DEEPSEEK_URL,
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]
```
**Why good**: Single responsibility, clear naming, raises on error (caller handles).

## Anti-Patterns (DO NOT)

1. **No `print()` in production code** — Use logging or SSE events for status. `print()` is acceptable only in `__main__` startup messages.

2. **No `any` type in Python** — Use specific types or `dict[str, Any]` at minimum. No `-> None` hiding complex returns.

3. **No bare `except Exception: pass`** — Always log or re-raise. Silent failures make debugging impossible. The only acceptable `pass` is in `_delete_file()` where file may not exist.

4. **No hardcoded paths or secrets** — All config via `.env` + `os.getenv()`. Never commit API keys, never hardcode ports.

5. **No blocking I/O in route handlers** — Heavy work (transcription, API calls) goes to background threads. Route handlers return quickly.

6. **No direct SQL or database** — This project uses in-memory state only. If persistence is needed, use SQLite with a migration to a proper pattern.

7. **No `console.log` in frontend production code** — The frontend has zero debug logging. Keep it clean.

## Code Quality Rules (for NEW code)

These rules apply to all new or modified code. Pre-existing code may violate them.

### Imports
- All imports at the top of the file, sorted: stdlib → third-party → local
- No `import` inside `if` blocks (except lazy model loading in `get_model()`)
- Use `from X import Y` for Flask, `import X` for stdlib

### Error Handling
- Use `contextlib.suppress(ExceptionType)` instead of `try: ... except: pass`
- Route handlers: return `jsonify({"error": "..."}), 4xx/5xx`
- Background threads: catch all exceptions, set error status in job dict
- Always log errors before returning or re-raising

### Type Annotations
- Module-level dicts must have type hints: `conversations: dict[str, list[dict]] = {}`
- Function signatures: prefer type hints but not required for Flask routes
- Use `dict[str, Any]` for JSON payloads, never `any`

### Route Handlers
- Validate input early, return 400 with clear error message
- Use `request.get_json()` for POST body, `request.files` for uploads
- Return JSON with consistent shape: `{"error": "..."}` or `{"key": "value"}`
- Use 502 for upstream API errors, 404 for not found, 400 for bad input

### File Operations
- Always check `os.path.exists()` before `os.remove()`
- Use `try: os.remove(path) except OSError: pass` for cleanup
- Sanitize filenames, enforce size limits

## Template: Typical Python File

```python
import os
import uuid
from typing import Any

import httpx
from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# --- Constants ---
API_URL = os.getenv("API_URL", "http://default")
TIMEOUT = 30

# --- State ---
items: dict[str, dict[str, Any]] = {}
items_lock = __import__("threading").Lock()

# --- Private helpers ---
def _validate(data: dict[str, Any]) -> bool:
    if not data or "name" not in data:
        return False
    return True

# --- Routes ---
@app.route("/api/items", methods=["GET"])
def list_items():
    with items_lock:
        result = list(items.values())
    return jsonify(result)

@app.route("/api/items", methods=["POST"])
def create_item():
    data = request.get_json()
    if not _validate(data):
        return jsonify({"error": "name is required"}), 400

    item_id = str(uuid.uuid4())
    with items_lock:
        items[item_id] = {"id": item_id, "name": data["name"]}
    return jsonify({"id": item_id}), 201

# --- Entry point ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
```

## Linting & Type Checking

```bash
# Run linter
ruff check .

# Run linter with auto-fix
ruff check --fix .

# Run type checker
mypy .
```

## Pre-existing Code Issues

The following issues exist in the original codebase and should be fixed over time:
- `import atexit` is not at top of file (E402)
- Module-level dicts lack type annotations (`conversations`, `stream_results`, `jobs`)
- Several `try: ... except: pass` blocks should use `contextlib.suppress()`
- Unused variable `elapsed` in `run_transcription_stream()`
- List concatenation `[...] + list` should use unpacking `[*..., *list]`

**When adding new code, do NOT introduce these patterns. Follow the Code Quality Rules above.**

## Commands

```bash
# Start main server (auto-starts MCP worker)
python server.py

# Start MCP worker standalone (for debugging)
python mcp_server.py

# Install dependencies
pip install -r requirements.txt
```
