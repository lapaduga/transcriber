import asyncio
import concurrent.futures
import json
import os
import threading

from dotenv import load_dotenv

load_dotenv()

VOSK_PORT = int(os.getenv("VOSK_PORT", 2700))
VOSK_MODEL_PATH = os.getenv("VOSK_MODEL_PATH", "models/vosk-model-ru-0.42")
SAMPLE_RATE = int(os.getenv("VOSK_SAMPLE_RATE", 16000))

model = None
pool = None
ready = False


def get_model():
    global model
    if model is None:
        from vosk import Model
        print(f"Vosk: загрузка модели из {VOSK_MODEL_PATH}...")
        model = Model(VOSK_MODEL_PATH)
        print("Vosk: модель загружена.")
    return model


def get_pool():
    global pool
    if pool is None:
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 1)
    return pool


def start_health_server():
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                if ready:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ready"}')
                else:
                    self.send_response(503)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"loading"}')
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("0.0.0.0", VOSK_PORT + 1), Handler)
    server.serve_forever()


async def recognize(websocket):
    from vosk import KaldiRecognizer

    m = get_model()
    p = get_pool()
    rec = KaldiRecognizer(m, SAMPLE_RATE)
    rec.SetWords(True)

    try:
        async for message in websocket:
            if isinstance(message, str):
                cmd = json.loads(message)
                if cmd.get("eof") == 1:
                    loop = asyncio.get_running_loop()
                    result = await loop.run_in_executor(p, rec.FinalResult)
                    await websocket.send(result)
                    break
                if cmd.get("config"):
                    if "sample_rate" in cmd["config"]:
                        rec = KaldiRecognizer(m, cmd["config"]["sample_rate"])
                        rec.SetWords(True)
                    continue

            loop = asyncio.get_running_loop()
            if rec.AcceptWaveform(message):
                result = await loop.run_in_executor(p, rec.Result)
                await websocket.send(result)
            else:
                partial = await loop.run_in_executor(p, rec.PartialResult)
                await websocket.send(partial)
    except Exception:
        pass


async def main():
    global ready
    import websockets

    get_model()

    threading.Thread(target=start_health_server, daemon=True).start()

    ready = True
    print(f"Vosk-сервер запущен на порту {VOSK_PORT} (модель: {VOSK_MODEL_PATH})")

    async with websockets.serve(recognize, "0.0.0.0", VOSK_PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
