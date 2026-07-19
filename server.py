import os
import sys
import uuid
import time
import json
import re
import signal
import subprocess
import threading
import httpx
import psutil
from flask import Flask, request, jsonify, Response, send_from_directory, stream_with_context
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

mcp_process = None
_cleaned = False


def start_mcp_server():
    global mcp_process
    mcp_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")
    mcp_process = subprocess.Popen(
        [sys.executable, mcp_script],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    time.sleep(1)
    print(f"MCP server started (PID {mcp_process.pid})")


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
import atexit

atexit.register(cleanup)

app = Flask(__name__, static_folder="public", static_url_path="")
CORS(app)

PORT = int(os.getenv("PORT", 3000))
MCP_PORT = int(os.getenv("MCP_PORT", 3001))
MCP_URL = f"http://127.0.0.1:{MCP_PORT}"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_FILE_SIZE = 500 * 1024 * 1024
ALLOWED_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma",
}

conversations = {}
stream_results = {}
stream_lock = threading.Lock()

TRANSCRIBE_TOOL = {
    "type": "function",
    "function": {
        "name": "transcribe_video",
        "description": "Transcribe audio or video file to text with timestamps.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the audio or video file",
                },
                "language": {
                    "type": "string",
                    "description": "Language code (auto, ru, en, etc.)",
                    "default": "auto",
                },
            },
            "required": ["file_path"],
        },
    },
}

SYSTEM_PROMPT = (
    "You are a video transcription assistant. You help users transcribe audio and video files. "
    "When a user provides a file path or uploads a file, use the transcribe_video tool to transcribe it. "
    "After receiving the transcription result (a Markdown table with timestamps and text), format it nicely. "
    "If the user asks a general question, answer it helpfully. "
    "Always respond in the language the user writes in."
)


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\.{2,}", ".", name)
    name = name.strip(". ")
    return (name or "file")[:200]


def allowed_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS


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


def _delete_file(path):
    try:
        if path and os.path.exists(path) and path.startswith(UPLOAD_DIR):
            os.remove(path)
    except OSError:
        pass


def _elapsed(job_id):
    with stream_lock:
        data = stream_results.get(job_id)
        if not data or "start_time" not in data:
            return 0
        return time.time() - data["start_time"]


def _format_duration(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def run_transcription_stream(job_id, conversation_id, user_message, file_path, language="auto"):
    try:
        with stream_lock:
            stream_results[job_id]["status"] = "running"
            stream_results[job_id]["phase"] = "Loading model..."
            stream_results[job_id]["start_time"] = time.time()

        mcp_resp = httpx.post(f"{MCP_URL}/call", json={"file_path": file_path, "language": language}, timeout=10)
        mcp_resp.raise_for_status()
        mcp_job_id = mcp_resp.json()["job_id"]

        with stream_lock:
            stream_results[job_id]["mcp_job_id"] = mcp_job_id

        while True:
            with stream_lock:
                if stream_results[job_id].get("cancelled"):
                    _delete_file(file_path)
                    return

            try:
                job_resp = httpx.get(f"{MCP_URL}/job/{mcp_job_id}", timeout=5)
                job_data = job_resp.json()

                with stream_lock:
                    stream_results[job_id]["progress"] = job_data.get("progress", 0)
                    stream_results[job_id]["phase"] = job_data.get("phase", "Processing...")

                if job_data["status"] in ("done", "error"):
                    break
            except Exception:
                pass

            time.sleep(1)

        if job_data["status"] == "error":
            error_msg = job_data.get("result", "Unknown transcription error")
            with stream_lock:
                stream_results[job_id]["status"] = "error"
                stream_results[job_id]["message"] = f"Transcription failed: {error_msg}"
            _delete_file(file_path)
            return

        transcription = job_data.get("result", "No result")

        with stream_lock:
            stream_results[job_id]["phase"] = "Formatting..."
            stream_results[job_id]["progress"] = 0.95

        conv = conversations.get(conversation_id, [])
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conv[-20:]
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": f"call_{job_id}",
                "type": "function",
                "function": {
                    "name": "transcribe_video",
                    "arguments": json.dumps({"file_path": file_path, "language": language}),
                },
            }],
        })
        messages.append({"role": "tool", "tool_call_id": f"call_{job_id}", "content": transcription})

        try:
            fmt = _deepseek(messages)
            assistant_msg = fmt.get("content", transcription)
        except Exception:
            assistant_msg = transcription

        elapsed = _elapsed(job_id)

        if conversation_id in conversations:
            conversations[conversation_id].append({"role": "assistant", "content": assistant_msg})

        with stream_lock:
            stream_results[job_id]["status"] = "done"
            stream_results[job_id]["progress"] = 1.0
            stream_results[job_id]["phase"] = "Done"
            stream_results[job_id]["message"] = assistant_msg

        _delete_file(file_path)

    except Exception as e:
        with stream_lock:
            stream_results[job_id]["status"] = "error"
            stream_results[job_id]["message"] = f"Error: {e}"
        _delete_file(file_path)


@app.route("/")
def index():
    return send_from_directory("public", "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("public", path)


@app.route("/api/health")
def health():
    mcp_ok = False
    deepseek_ok = bool(DEEPSEEK_API_KEY and DEEPSEEK_API_KEY != "your_deepseek_api_key_here")
    try:
        r = httpx.get(f"{MCP_URL}/tools", timeout=3)
        mcp_ok = r.status_code == 200
    except Exception:
        pass
    return jsonify({"ok": True, "mcp": mcp_ok, "deepseek": deepseek_ok})


@app.route("/api/stats")
def stats():
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    result = {
        "cpu": round(cpu, 1),
        "ram_used": round(mem.used / (1024 ** 3), 1),
        "ram_total": round(mem.total / (1024 ** 3), 1),
        "ram_percent": round(mem.percent, 1),
        "gpu_used": None,
        "gpu_total": None,
    }
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            timeout=3, stderr=subprocess.DEVNULL,
        ).decode().strip().split(",")
        result["gpu_used"] = round(int(out[0].strip()) / 1024, 1)
        result["gpu_total"] = round(int(out[1].strip()) / 1024, 1)
    except Exception:
        pass
    return jsonify(result)


@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": f"File type not allowed"}), 400

    file.seek(0, 2)
    size = file.tell()
    file.seek(0)

    if size > MAX_FILE_SIZE:
        return jsonify({"error": f"File too large (max {MAX_FILE_SIZE // (1024 * 1024)} MB)"}), 400

    file_id = str(uuid.uuid4())
    safe_name = sanitize_filename(file.filename)
    ext = os.path.splitext(safe_name)[1]
    save_path = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")
    file.save(save_path)

    return jsonify({"file_id": file_id, "path": save_path, "name": safe_name, "size": size})


@app.route("/api/stream/<job_id>")
def sse_stream(job_id):
    def generate():
        while True:
            with stream_lock:
                data = stream_results.get(job_id)

            if not data:
                yield f"data: {json.dumps({'status': 'error', 'message': 'Job not found'})}\n\n"
                break

            elapsed = time.time() - data.get("start_time", time.time()) if data.get("start_time") else 0

            event = {
                "status": data["status"],
                "progress": data["progress"],
                "phase": data["phase"],
                "message": data["message"],
                "error": data.get("error"),
                "elapsed": round(elapsed),
            }
            if data["status"] == "done":
                event["duration"] = _format_duration(elapsed)
            yield f"data: {json.dumps(event)}\n\n"

            if data["status"] in ("done", "error", "cancelled"):
                break

            time.sleep(1)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.route("/api/cancel/<job_id>", methods=["POST"])
def cancel_job(job_id):
    with stream_lock:
        data = stream_results.get(job_id)
        if not data:
            return jsonify({"error": "Job not found"}), 404

        if data["status"] in ("done", "error", "cancelled"):
            return jsonify({"ok": True, "status": data["status"]})

        data["cancelled"] = True
        data["status"] = "cancelled"
        data["phase"] = "Cancelled"
        data["message"] = "Transcription cancelled."

        mcp_job_id = data.get("mcp_job_id")
        file_path = data.get("file_path")

    if mcp_job_id:
        try:
            httpx.post(f"{MCP_URL}/cancel/{mcp_job_id}", timeout=5)
        except Exception:
            pass

    if file_path:
        _delete_file(file_path)

    if conversation_id := data.get("conversation_id"):
        if conversation_id in conversations:
            conversations[conversation_id].append({"role": "assistant", "content": "Transcription cancelled."})

    return jsonify({"ok": True})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "message is required"}), 400

    user_message = data["message"]
    conversation_id = data.get("conversation_id", str(uuid.uuid4()))
    file_path = data.get("file_path")

    if conversation_id not in conversations:
        conversations[conversation_id] = []

    conversations[conversation_id].append({"role": "user", "content": user_message})

    if file_path:
        if not os.path.exists(file_path):
            conversations[conversation_id].pop()
            return jsonify({"error": "File not found"}), 400

        job_id = str(uuid.uuid4())
        with stream_lock:
            stream_results[job_id] = {
                "status": "starting",
                "progress": 0.0,
                "phase": "Initializing...",
                "message": None,
                "error": None,
                "mcp_job_id": None,
                "file_path": file_path,
                "conversation_id": conversation_id,
                "start_time": time.time(),
                "cancelled": False,
            }

        thread = threading.Thread(
            target=run_transcription_stream,
            args=(job_id, conversation_id, user_message, file_path),
            daemon=True,
        )
        thread.start()

        return jsonify({"job_id": job_id, "conversation_id": conversation_id})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversations[conversation_id][-20:]

    try:
        message = _deepseek(messages, tools=[TRANSCRIBE_TOOL])
    except httpx.HTTPStatusError as e:
        conversations[conversation_id].pop()
        return jsonify({"error": f"DeepSeek API error: {e.response.status_code}"}), 502
    except Exception as e:
        conversations[conversation_id].pop()
        return jsonify({"error": f"DeepSeek connection error: {e}"}), 502

    if message.get("tool_calls"):
        tc = message["tool_calls"][0]
        args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
        extracted = args.get("file_path")
        if extracted and os.path.exists(extracted):
            conversations[conversation_id].pop()
            job_id = str(uuid.uuid4())
            with stream_lock:
                stream_results[job_id] = {
                    "status": "starting",
                    "progress": 0.0,
                    "phase": "Initializing...",
                    "message": None,
                    "error": None,
                    "mcp_job_id": None,
                    "file_path": extracted,
                    "conversation_id": conversation_id,
                    "start_time": time.time(),
                    "cancelled": False,
                }
            thread = threading.Thread(
                target=run_transcription_stream,
                args=(job_id, conversation_id, user_message, extracted, args.get("language", "auto")),
                daemon=True,
            )
            thread.start()
            return jsonify({"job_id": job_id, "conversation_id": conversation_id})

        assistant_msg = "Please provide a valid file path or upload a file."
        conversations[conversation_id].append({"role": "assistant", "content": assistant_msg})
        return jsonify({"message": assistant_msg, "conversation_id": conversation_id})

    assistant_msg = message.get("content", "")
    conversations[conversation_id].append({"role": "assistant", "content": assistant_msg})
    return jsonify({"message": assistant_msg, "conversation_id": conversation_id})


if __name__ == "__main__":
    start_mcp_server()
    print(f"Server running on http://127.0.0.1:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
