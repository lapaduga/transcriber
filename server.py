import atexit
import json
import mimetypes
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid

import edge_tts
import httpx
import psutil
from dotenv import load_dotenv
from flask_cors import CORS

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

load_dotenv()

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

mcp_process = None
vosk_process = None
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
    print(f"MCP-сервер запущен (PID {mcp_process.pid})")


def start_vosk_server():
    global vosk_process
    vosk_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vosk_server.py")
    vosk_process = subprocess.Popen(
        [sys.executable, vosk_script],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    time.sleep(1)
    print(f"Vosk-сервер запущен (PID {vosk_process.pid})")


def cleanup(signum=None, frame=None):
    global mcp_process, vosk_process, _cleaned
    if _cleaned:
        return
    _cleaned = True
    if mcp_process and mcp_process.poll() is None:
        print("\nОстановка MCP-сервера...")
        mcp_process.terminate()
        try:
            mcp_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mcp_process.kill()
    if vosk_process and vosk_process.poll() is None:
        print("Остановка Vosk-сервера...")
        vosk_process.terminate()
        try:
            vosk_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            vosk_process.kill()
    print("Готово.")


signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

atexit.register(cleanup)

app = Flask(__name__, static_folder="public", static_url_path="")
CORS(app)

PORT = int(os.getenv("PORT", 3000))
MCP_PORT = int(os.getenv("MCP_PORT", 3001))
MCP_URL = f"http://127.0.0.1:{MCP_PORT}"
VOSK_PORT = int(os.getenv("VOSK_PORT", 2700))
VOSK_HEALTH_URL = f"http://127.0.0.1:{VOSK_PORT + 1}/health"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
TTS_VOICE = os.getenv("TTS_VOICE", "ru-RU-DmitryNeural")
TTS_RATE = os.getenv("TTS_RATE", "+20%")

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

for _f in os.listdir(UPLOAD_DIR):
    _fp = os.path.join(UPLOAD_DIR, _f)
    if os.path.isfile(_fp):
        os.remove(_fp)

MAX_FILE_SIZE = 500 * 1024 * 1024
ALLOWED_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma",
}

conversations = {}
stream_results = {}
stream_lock = threading.Lock()
MAX_CONVERSATIONS = 50

TRANSCRIBE_TOOL = {
    "type": "function",
    "function": {
        "name": "transcribe_video",
        "description": "Транскрибировать аудио или видеофайл в текст с таймкодами.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Абсолютный путь к аудио или видеофайлу",
                },
                "language": {
                    "type": "string",
                    "description": "Код языка (auto, ru, en и т.д.)",
                    "default": "auto",
                },
            },
            "required": ["file_path"],
        },
    },
}

SUMMARIZE_TOOL = {
    "type": "function",
    "function": {
        "name": "summarize_text",
        "description": "Сделать краткую саммари транскрипции или длинного текста.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Текст транскрипции или длинный текст для саммари",
                },
                "language": {
                    "type": "string",
                    "description": "Код языка для саммари (en, ru и т.д.)",
                    "default": "en",
                },
            },
            "required": ["text"],
        },
    },
}

SYSTEM_PROMPT = (
    "Ты — ассистент для транскрипции видео. Ты помогаешь пользователям транскрибировать аудио и видеофайлы. "
    "Когда пользователь указывает путь к файлу или загружает файл, используй инструмент transcribe_video для транскрипции. "
    "После получения результата транскрипции (таблица Markdown с таймкодами и текстом), оформи его красиво. "
    "Если пользователь задает общий вопрос, ответь полезно. "
    "Всегда отвечай на языке, на котором пишет пользователь."
)


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\.{2,}", ".", name)
    name = name.strip(". ")
    return (name or "file")[:200]


def allowed_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS


def _sanitize_for_tts(text):
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\|.*\|$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[|\-:\s]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\|{2,}", " ", text)
    text = re.sub(r"[#/\\|_~`^<>(){}[\]!@#$%&=+;:\"',.?]", " ", text)
    text = re.sub(
        r"[\U0001F600-\U0001F64F"
        r"\U0001F300-\U0001F5FF"
        r"\U0001F680-\U0001F6FF"
        r"\U0001F1E0-\U0001F1FF"
        r"\U00002702-\U000027B0"
        r"\U0000FE00-\U0000FE0F"
        r"\U0000200D"
        r"\U000024C2-\U0001F251"
        r"\U0001F900-\U0001F9FF"
        r"\U0001FA00-\U0001FA6F"
        r"\U0001FA70-\U0001FAFF"
        r"\U00002600-\U000026FF"
        r"\U00002300-\U000023FF"
        r"\U0000203C-\U00003299"
        r"]+", "", text
    )
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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
            stream_results[job_id]["phase"] = "Загрузка модели..."
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
                    stream_results[job_id]["phase"] = job_data.get("phase", "Обработка...")

                if job_data["status"] in ("done", "error"):
                    break
            except Exception:
                pass

            time.sleep(1)

        if job_data["status"] == "error":
            error_msg = job_data.get("result", "Неизвестная ошибка транскрипции")
            with stream_lock:
                stream_results[job_id]["status"] = "error"
                stream_results[job_id]["message"] = f"Ошибка транскрипции: {error_msg}"
            _delete_file(file_path)
            return

        transcription = job_data.get("result", "Нет результата")

        with stream_lock:
            stream_results[job_id]["phase"] = "Форматирование..."
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

        if conversation_id in conversations:
            conversations[conversation_id].append({"role": "assistant", "content": assistant_msg})

        with stream_lock:
            stream_results[job_id]["status"] = "done"
            stream_results[job_id]["progress"] = 1.0
            stream_results[job_id]["phase"] = "Готово"
            stream_results[job_id]["message"] = assistant_msg

        _delete_file(file_path)

    except Exception as e:
        with stream_lock:
            stream_results[job_id]["status"] = "error"
            stream_results[job_id]["message"] = f"Ошибка: {e}"
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
    vosk_ok = False
    deepseek_ok = bool(DEEPSEEK_API_KEY and DEEPSEEK_API_KEY != "your_deepseek_api_key_here")
    try:
        r = httpx.get(f"{MCP_URL}/tools", timeout=3)
        mcp_ok = r.status_code == 200
    except Exception:
        pass
    try:
        r = httpx.get(VOSK_HEALTH_URL, timeout=3)
        vosk_ok = r.status_code == 200
    except Exception:
        pass
    return jsonify({"ok": True, "mcp": mcp_ok, "vosk": vosk_ok, "deepseek": deepseek_ok})


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
        return jsonify({"error": "Файл не предоставлен"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Файл не выбран"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Тип файла не поддерживается"}), 400

    file.seek(0, 2)
    size = file.tell()
    file.seek(0)

    if size > MAX_FILE_SIZE:
        return jsonify({"error": f"Файл слишком большой (максимум {MAX_FILE_SIZE // (1024 * 1024)} МБ)"}), 400

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
                yield f"data: {json.dumps({'status': 'error', 'message': 'Задача не найдена'})}\n\n"
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
                with stream_lock:
                    stream_results.pop(job_id, None)
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
            return jsonify({"error": "Задача не найдена"}), 404

        if data["status"] in ("done", "error", "cancelled"):
            return jsonify({"ok": True, "status": data["status"]})

        data["cancelled"] = True
        data["status"] = "cancelled"
        data["phase"] = "Отменено"
        data["message"] = "Транскрипция отменена."

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
            conversations[conversation_id].append({"role": "assistant", "content": "Транскрипция отменена."})

    return jsonify({"ok": True})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Обязательное поле message"}), 400

    user_message = data["message"]
    conversation_id = data.get("conversation_id", str(uuid.uuid4()))
    file_path = data.get("file_path")

    if conversation_id not in conversations:
        if len(conversations) >= MAX_CONVERSATIONS:
            oldest = next(iter(conversations))
            del conversations[oldest]
        conversations[conversation_id] = []

    conversations[conversation_id].append({"role": "user", "content": user_message})

    if file_path:
        if not os.path.exists(file_path):
            conversations[conversation_id].pop()
            return jsonify({"error": "Файл не найден"}), 400

        job_id = str(uuid.uuid4())
        with stream_lock:
            stream_results[job_id] = {
                "status": "starting",
                "progress": 0.0,
                "phase": "Инициализация...",
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
        message = _deepseek(messages, tools=[TRANSCRIBE_TOOL, SUMMARIZE_TOOL])
    except httpx.HTTPStatusError as e:
        conversations[conversation_id].pop()
        return jsonify({"error": f"Ошибка API DeepSeek: {e.response.status_code}"}), 502
    except Exception as e:
        conversations[conversation_id].pop()
        return jsonify({"error": f"Ошибка подключения к DeepSeek: {e}"}), 502

    if message.get("tool_calls"):
        tc = message["tool_calls"][0]
        args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
        tool_name = tc["function"]["name"]

        if tool_name == "summarize_text":
            text = args.get("text", "").strip()
            language = args.get("language", "en")
            if not text:
                assistant_msg = "Текст для саммари не предоставлен."
                conversations[conversation_id].append({"role": "assistant", "content": assistant_msg})
                return jsonify({"message": assistant_msg, "conversation_id": conversation_id})

            messages_summary = [
                {"role": "system", "content": f"Сделай краткую саммари следующего текста на языке {language}. "
                 "Верни простой текст, без таблиц Markdown."},
                {"role": "user", "content": text},
            ]
            try:
                reply = _deepseek(messages_summary)
                assistant_msg = reply.get("content", "Не удалось создать саммари.")
            except Exception as e:
                assistant_msg = f"Ошибка саммари: {e}"

            conversations[conversation_id].append({"role": "assistant", "content": assistant_msg})
            return jsonify({"message": assistant_msg, "conversation_id": conversation_id})

        extracted = args.get("file_path")
        if extracted and os.path.exists(extracted):
            conversations[conversation_id].pop()
            job_id = str(uuid.uuid4())
            with stream_lock:
                stream_results[job_id] = {
                    "status": "starting",
                    "progress": 0.0,
                    "phase": "Инициализация...",
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

        assistant_msg = "Укажите путь к файлу или загрузите файл."
        conversations[conversation_id].append({"role": "assistant", "content": assistant_msg})
        return jsonify({"message": assistant_msg, "conversation_id": conversation_id})

    assistant_msg = message.get("content", "")
    conversations[conversation_id].append({"role": "assistant", "content": assistant_msg})
    return jsonify({"message": assistant_msg, "conversation_id": conversation_id})


@app.route("/api/summarize", methods=["POST"])
def summarize():
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"error": "Обязательное поле text"}), 400

    text = data["text"].strip()
    if not text:
        return jsonify({"error": "Текст не должен быть пустым"}), 400

    language = data.get("language", "en")

    messages = [
        {"role": "system", "content": f"Сделай краткую саммари следующей транскрипции на языке {language}. "
         "Верни простой текст, без таблиц Markdown."},
        {"role": "user", "content": text},
    ]

    try:
        reply = _deepseek(messages)
    except httpx.HTTPStatusError as e:
        return jsonify({"error": f"Ошибка API DeepSeek: {e.response.status_code}"}), 502
    except Exception as e:
        return jsonify({"error": f"Ошибка подключения к DeepSeek: {e}"}), 502

    summary = reply.get("content", "")
    return jsonify({"summary": summary, "language": language})


@app.route("/api/tts", methods=["POST"])
def tts():
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"error": "Обязательное поле text"}), 400

    text = data["text"].strip()
    if not text:
        return jsonify({"error": "Текст не должен быть пустым"}), 400

    voice = data.get("voice", TTS_VOICE)
    rate = data.get("rate", TTS_RATE)
    clean = _sanitize_for_tts(text)

    try:
        communicate = edge_tts.Communicate(clean, voice, rate=rate)
        audio_parts = []
        for chunk in communicate.stream_sync():
            if chunk["type"] == "audio":
                audio_parts.append(chunk["data"])
        audio_data = b"".join(audio_parts)
        if not audio_data:
            return jsonify({"error": "TTS не вернул аудио"}), 500
    except Exception as e:
        return jsonify({"error": f"TTS ошибка: {e}"}), 500

    return Response(
        audio_data,
        mimetype="audio/mpeg",
        headers={"Cache-Control": "no-cache", "Content-Disposition": "inline"},
    )


if __name__ == "__main__":
    import webbrowser

    def _open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://127.0.0.1:{PORT}")

    threading.Thread(target=_open_browser, daemon=True).start()

    start_mcp_server()
    start_vosk_server()
    print(f"Сервер запущен на http://127.0.0.1:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
