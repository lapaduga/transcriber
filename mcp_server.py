import os
import threading
import uuid

from dotenv import load_dotenv

from flask import Flask, jsonify, request

load_dotenv()

app = Flask(__name__)

MCP_PORT = int(os.getenv("MCP_PORT", 3001))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")

model = None
model_lock = threading.Lock()
jobs = {}
jobs_lock = threading.Lock()
MAX_JOBS = 100

TOOLS = [
    {
        "name": "transcribe_video",
        "description": "Транскрибировать аудио или видеофайл в текст с таймкодами",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Абсолютный путь к аудио или видеофайлу"},
                "language": {"type": "string", "description": "Код языка (auto, ru, en и т.д.)", "default": "auto"},
            },
            "required": ["file_path"],
        },
    }
]


def get_model():
    global model
    if model is None:
        with model_lock:
            if model is None:
                from faster_whisper import WhisperModel
                model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return model


def run_transcription(job_id, file_path, language):
    try:
        with jobs_lock:
            jobs[job_id]["status"] = "running"
            jobs[job_id]["phase"] = "загрузка модели"
            jobs[job_id]["progress"] = 0.0

        m = get_model()

        with jobs_lock:
            jobs[job_id]["phase"] = "транскрипция"

        segments, info = m.transcribe(
            file_path,
            language=language if language != "auto" else None,
            word_timestamps=True,
            vad_filter=True,
        )

        total_duration = 0
        try:
            total_duration = info.duration
        except Exception:
            pass
        if not total_duration or total_duration <= 0:
            try:
                import av as _av
                container = _av.open(file_path)
                total_duration = float(container.duration / 1_000_000) if container.duration else 0
                container.close()
            except Exception:
                total_duration = 0

        result_lines = []
        segment_count = 0
        for seg in segments:
            with jobs_lock:
                if jobs[job_id].get("cancelled"):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
                    return

            start = seg.start
            end = seg.end
            text = seg.text.strip()
            segment_count += 1

            sh, sm, ss = int(start // 3600), int((start % 3600) // 60), start % 60
            eh, em, es = int(end // 3600), int((end % 3600) // 60), end % 60

            if sh > 0:
                time_str = f"{sh:02d}:{sm:02d}:{ss:05.2f} → {eh:02d}:{em:02d}:{es:05.2f}"
            else:
                time_str = f"{sm:02d}:{ss:05.2f} → {em:02d}:{es:05.2f}"

            result_lines.append(f"| {time_str} | {text} |")

            if total_duration > 0:
                progress = min(end / total_duration, 0.95)
            else:
                progress = min(segment_count * 0.05, 0.95)
            with jobs_lock:
                jobs[job_id]["progress"] = progress

        header = "| Время | Текст |\n|------|------|\n"
        markdown = header + "\n".join(result_lines) if result_lines else "_Речь не обнаружена._"

        with jobs_lock:
            jobs[job_id]["status"] = "done"
            jobs[job_id]["phase"] = "завершено"
            jobs[job_id]["progress"] = 1.0
            jobs[job_id]["result"] = markdown

        try:
            os.remove(file_path)
        except OSError:
            pass

    except Exception as e:
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["phase"] = "error"
            jobs[job_id]["result"] = str(e)

    with jobs_lock:
        if len(jobs) > MAX_JOBS:
            done_ids = [jid for jid, j in jobs.items() if j["status"] in ("done", "error", "cancelled")]
            for jid in done_ids[: len(done_ids) - MAX_JOBS + 10]:
                jobs.pop(jid, None)


@app.route("/tools", methods=["GET"])
def list_tools():
    return jsonify({"tools": TOOLS})


@app.route("/call", methods=["POST"])
def call_tool():
    data = request.get_json()
    if not data or "file_path" not in data:
        return jsonify({"error": "Обязательное поле file_path"}), 400

    file_path = data["file_path"]
    language = data.get("language", "auto")

    if not os.path.exists(file_path):
        return jsonify({"error": "Файл не найден"}), 404

    job_id = str(uuid.uuid4())

    with jobs_lock:
        jobs[job_id] = {
            "status": "starting",
            "progress": 0.0,
            "phase": "queued",
            "result": None,
            "file_path": file_path,
            "cancelled": False,
        }

    thread = threading.Thread(target=run_transcription, args=(job_id, file_path, language), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/job/<job_id>", methods=["GET"])
def get_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "progress": job["progress"],
        "phase": job["phase"],
        "result": job["result"],
    })


@app.route("/cancel/<job_id>", methods=["POST"])
def cancel_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        if job["status"] in ("done", "error", "cancelled"):
            return jsonify({"ok": True, "status": job["status"]})
        job["cancelled"] = True
        job["status"] = "cancelled"
        job["phase"] = "cancelled"
        file_path = job.get("file_path")

    if file_path:
        try:
            os.remove(file_path)
        except OSError:
            pass

    return jsonify({"ok": True})


if __name__ == "__main__":
    print(f"MCP-сервер запущен на порту {MCP_PORT}")
    app.run(host="0.0.0.0", port=MCP_PORT, debug=False)
