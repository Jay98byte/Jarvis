"""Local web bridge for the Jarvis Workplace HUD."""

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import psutil

import jarvis_brain
import jarvis_actions
import jarvis_market
import jarvis_voice


HOST = "127.0.0.1"
PORT = 8765
API_VERSION = 3
HTML_PATH = Path(__file__).with_name("jarvis_workplace.html")
MAX_BODY = 8192
SYSTEM_REFRESH_INTERVAL = 1.0


class WorkplaceState:
    def __init__(self):
        self.lock = threading.RLock()
        self.command_lock = threading.Lock()
        self.listener_lock = threading.Lock()
        self.listener_stop = threading.Event()
        self.listener_thread = None
        self.restart_requested = False
        self.suspend_listening = threading.Event()
        self.pause_threshold = 1.0
        self.started_at = time.monotonic()
        self._system_update_lock = threading.Lock()
        self._system_updated_at = None
        self.chat_id = 0
        self.data = {
            "app": "jarvis-workplace",
            "api_version": API_VERSION,
            "state": "idle",
            "note": "Ready",
            "mode": "LOCAL + GROQ",
            "api_configured": bool(jarvis_brain._get_api_key()),
            "last_you": "",
            "t_rec": 0.0,
            "t_think": 0.0,
            "last_tool": "Ready",
            "tools": 0,
            "facts": 0,
            "mail_age": None,
            "tool_active": False,
            "chat": [],
            "cards": [],
            "stocks": [],
            "sys": {},
            "mic": {"n": 0, "a": []},
        }
        self.update_system()

    def add_chat(self, kind, message, source=""):
        with self.lock:
            self.chat_id += 1
            self.data["chat"].append({
                "i": self.chat_id,
                "k": kind,
                "x": str(message)[:2000],
                "t": datetime.now().strftime("%H:%M:%S"),
                "source": source,
            })
            self.data["chat"] = self.data["chat"][-80:]

    def update_status(self, status, note=""):
        with self.lock:
            self.data["state"] = status
            self.data["note"] = str(note)[:200]
        if status in ("thinking", "speaking"):
            self.suspend_listening.set()
        elif status in ("listening", "idle", "off"):
            self.suspend_listening.clear()

    def set_listening(self, enabled):
        if not enabled:
            self.listener_stop.set()
            with self.listener_lock:
                self.restart_requested = False
            self.update_status("idle", "Microphone stopped")
            return
        with self.listener_lock:
            if self.listener_thread and self.listener_thread.is_alive():
                if self.listener_stop.is_set():
                    self.restart_requested = True
                    self.update_status("starting", "Restarting microphone")
                    return
                self.update_status("listening", "Microphone is listening")
                return
            self.listener_stop = threading.Event()
            self.restart_requested = False
            self.suspend_listening.clear()
            self.update_status("starting", "Opening microphone")
            self.listener_thread = threading.Thread(
                target=self._listen_loop,
                args=(self.listener_stop,),
                name="jarvis-workplace-listener",
                daemon=True,
            )
            self.listener_thread.start()

    def _listen_loop(self, stop_event):
        recognizer = jarvis_voice.sr.Recognizer()
        jarvis_voice.configure_recognizer(recognizer)
        try:
            microphone = jarvis_voice._create_microphone()
            with microphone as source:
                recognizer.adjust_for_ambient_noise(source, duration=1.0)
                if stop_event.is_set():
                    return
                self.update_status("listening", "Microphone is listening")
                while not stop_event.is_set():
                    if self.suspend_listening.wait(0.1):
                        continue
                    with self.lock:
                        pause_threshold = self.pause_threshold
                    jarvis_voice.configure_recognizer(recognizer, pause_threshold)
                    try:
                        audio = recognizer.listen(
                            source,
                            timeout=1,
                            phrase_time_limit=jarvis_voice.LISTEN_PHRASE_TIME_LIMIT,
                        )
                    except jarvis_voice.sr.WaitTimeoutError:
                        continue
                    if stop_event.is_set() or self.suspend_listening.is_set():
                        continue
                    self.update_status("recognizing", "Recognizing speech")
                    try:
                        query = recognizer.recognize_google(audio).strip()
                    except jarvis_voice.sr.UnknownValueError:
                        self.update_status("listening", "Microphone is listening")
                        continue
                    except jarvis_voice.sr.RequestError as exc:
                        self.add_chat("sys", f"Speech recognition request failed: {exc}")
                        self.update_status("listening", "Speech recognition service unavailable")
                        time.sleep(1)
                        continue
                    query = re.sub(r"^jarvis[\s,.:!-]*", "", query, flags=re.IGNORECASE).strip()
                    if not query:
                        self.update_status("listening", "Microphone is listening")
                        continue
                    if re.sub(r"[\W_]+", " ", query.lower()).strip() in {
                        "cooldown", "cool down", "close workplace",
                    }:
                        self.add_chat("you", query, source="voice")
                        self.add_chat(
                            "jarvis",
                            "Jarvis is standing by. You can close this tab when you are ready.",
                            source="voice",
                        )
                        self.update_status("off", "Jarvis is standing by")
                        stop_event.set()
                        break
                    self.run_command(query, source="voice")
        except Exception as exc:
            print(f"[Microphone error] {exc}", flush=True)
            self.add_chat("sys", f"Microphone unavailable: {exc}")
            self.update_status("off", "Check microphone access and the bridge log")
        finally:
            if not stop_event.is_set():
                self.update_status("off", "Microphone stopped")
                stop_event.set()
            with self.listener_lock:
                if self.listener_thread is threading.current_thread():
                    self.listener_thread = None
                    restart = self.restart_requested
                    self.restart_requested = False
                else:
                    restart = False
            if restart:
                self.set_listening(True)

    def update_system(self):
        with self._system_update_lock:
            now = time.monotonic()
            # The HUD polls every 400 ms, faster than these system metrics need refreshing.
            if (
                self._system_updated_at is not None
                and now - self._system_updated_at < SYSTEM_REFRESH_INTERVAL
            ):
                return

            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(os.path.abspath(os.sep))
            battery = psutil.sensors_battery()
            system_data = {
                "cpu": psutil.cpu_percent(),
                "ram": memory.percent,
                "disk": disk.percent,
                "free": round(disk.free / (1024 ** 3), 1),
                "up": int(now - self.started_at),
            }
            if battery is not None:
                system_data["bat"] = round(battery.percent)
                system_data["plug"] = battery.power_plugged

            with self.lock:
                self.data["sys"] = system_data
            self._system_updated_at = time.monotonic()

    def snapshot(self):
        self.update_system()
        with self.lock:
            return json.loads(json.dumps(self.data))

    def run_command(self, query, source="text"):
        with self.command_lock:
            self.add_chat("you", query, source=source)
            with self.lock:
                self.data["last_you"] = query
                self.data["state"] = "thinking"
                self.data["note"] = "Processing command"
                self.data["mode"] = "GROQ + LOCAL" if jarvis_brain.ready() else "LOCAL MODE"
            self.suspend_listening.set()
            started = time.monotonic()
            try:
                response = jarvis_brain.think(query)
                if not isinstance(response, str) or not response.strip():
                    raise RuntimeError("The assistant returned an empty response.")
            except Exception:
                self.update_status("idle", "Command failed; check the local bridge log")
                raise
            elapsed = time.monotonic() - started
            self.add_chat("jarvis", response, source=source)
            with self.lock:
                self.data["t_think"] = round(elapsed, 2)
                self.data["tools"] += 1
                self.data["last_tool"] = "Local action / AI"
                self.data["state"] = "speaking"
                self.data["note"] = "Response ready"
            self.suspend_listening.set()
            return response

    def refresh_market(self):
        try:
            reports = jarvis_market.get_market_watchlist()
            stocks = []
            for item in reports:
                stocks.append({
                    "sym": item["symbol"],
                    "name": item["name"],
                    "price": item["price"],
                    "pct": item["pct_change"],
                    "mom": item["pct_change"],
                    "above": item["pct_change"] >= 0,
                    "spark": [],
                    "stale": False,
                    "err": False,
                })
            with self.lock:
                self.data["stocks"] = stocks
        except Exception as exc:
            print(f"[Market refresh error] {exc}", flush=True)


STATE = WorkplaceState()


class WorkplaceHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


class WorkplaceHandler(BaseHTTPRequestHandler):
    server_version = "JarvisWorkplace/1.0"

    @property
    def app_state(self):
        return STATE

    def log_message(self, fmt, *args):
        if self.command == "GET" and self.path.startswith("/api/state"):
            return
        print(f"[HTTP] {self.address_string()} {fmt % args}", flush=True)

    def _send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _request_is_local(self):
        host = self.headers.get("Host", "").lower()
        if host not in (f"127.0.0.1:{PORT}", f"localhost:{PORT}"):
            return False
        try:
            return self.client_address[0] in ("127.0.0.1", "::1")
        except (IndexError, TypeError):
            return False

    def _origin_is_local(self):
        origin = self.headers.get("Origin")
        if not origin:
            return False
        parsed = urlsplit(origin)
        return (
            parsed.scheme == "http"
            and parsed.hostname in ("127.0.0.1", "localhost")
            and parsed.port == PORT
        )

    def _read_json(self):
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json.")
        raw_length = self.headers.get("Content-Length", "")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("A valid Content-Length is required.") from exc
        if length < 1 or length > MAX_BODY:
            raise ValueError("Request body must be between 1 and 8192 bytes.")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must contain valid JSON.") from exc

    def do_GET(self):
        if not self._request_is_local():
            self._send_json(403, {"error": "Local access only."})
            return

        path = urlsplit(self.path).path
        if path == "/api/state":
            self._send_json(200, self.app_state.snapshot())
            return
        if path in ("/", "/jarvis_workplace.html"):
            try:
                page = HTML_PATH.read_bytes()
            except OSError as exc:
                print(f"[HUD error] Could not read {HTML_PATH}: {exc}", flush=True)
                self._send_json(500, {"error": "Could not read the Workplace page."})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(page)
            return
        self._send_json(404, {"error": "Not found."})

    def do_POST(self):
        if not self._request_is_local() or not self._origin_is_local():
            self._send_json(403, {"error": "Requests must come from this local Jarvis page."})
            return

        path = urlsplit(self.path).path
        try:
            data = self._read_json()
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "A JSON object is required."})
            return

        if path == "/api/status":
            status = data.get("state")
            if status not in {
                "idle", "starting", "listening", "recognizing", "thinking",
                "speaking", "off",
            }:
                self._send_json(400, {"error": "Unsupported assistant state."})
                return
            self.app_state.update_status(status, data.get("note", ""))
            self._send_json(200, {"ok": True})
            return

        if path == "/api/listening-settings":
            pause_threshold = data.get("pause_threshold")
            if (
                isinstance(pause_threshold, bool)
                or not isinstance(pause_threshold, (int, float))
                or pause_threshold not in (0.5, 1, 1.5, 2)
            ):
                self._send_json(400, {
                    "error": "Choose an end-of-speech pause from 0.5, 1, 1.5, or 2 seconds.",
                })
                return
            with self.app_state.lock:
                self.app_state.pause_threshold = float(pause_threshold)
            self._send_json(200, {
                "ok": True,
                "pause_threshold": float(pause_threshold),
            })
            return

        if path == "/api/listening":
            enabled = data.get("enabled")
            if not isinstance(enabled, bool):
                self._send_json(400, {"error": "The enabled field must be true or false."})
                return
            self.app_state.set_listening(enabled)
            self._send_json(200, {"ok": True, "enabled": enabled})
            return

        if path == "/api/api-key":
            key = data.get("key")
            if not isinstance(key, str) or not key.strip() or len(key) > 500:
                self._send_json(400, {"error": "Enter a valid API key up to 500 characters."})
                return
            try:
                jarvis_brain.save_api_key(key)
            except (OSError, ValueError) as exc:
                print(f"[API key error] Could not save key: {exc}", flush=True)
                self._send_json(500, {"error": "Could not save the API key to the local Jarvis profile."})
                return
            with self.app_state.lock:
                self.app_state.data["api_configured"] = True
            self._send_json(200, {"ok": True})
            return

        if path == "/api/calendar/connect":
            client_id = data.get("client_id")
            client_secret = data.get("client_secret")
            if not isinstance(client_id, str) or not isinstance(client_secret, str):
                self._send_json(400, {"error": "Enter your Google OAuth client ID and client secret."})
                return
            response = jarvis_actions.configure_google_calendar(
                client_id, client_secret
            )
            if not response.startswith("Google Calendar connected."):
                self._send_json(400, {"error": response})
                return
            self._send_json(200, {"ok": True, "message": response})
            return

        if path == "/api/command":
            query = data.get("query")
            if not isinstance(query, str) or not query.strip() or len(query) > 1000:
                self._send_json(400, {"error": "Enter a command up to 1000 characters."})
                return
            try:
                response = self.app_state.run_command(query.strip())
            except Exception as exc:
                print(f"[Command error] {exc}", flush=True)
                self._send_json(500, {
                    "error": "Jarvis could not process that command. Check the bridge log.",
                })
                return
            self._send_json(200, {"response": response})
            return

        self._send_json(404, {"error": "Not found."})


def _existing_server_is_jarvis():
    url = f"http://{HOST}:{PORT}/api/state"
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            state = json.loads(response.read().decode("utf-8"))
        return (
            state.get("app") == "jarvis-workplace"
            and state.get("api_version") == API_VERSION
        )
    except (OSError, urllib.error.URLError, json.JSONDecodeError, AttributeError):
        return False


def main():
    show_hud = "--show" in sys.argv[1:]
    log_path = os.path.join(
        os.environ.get("APPDATA") or os.path.expanduser("~"),
        "OpenJarvis",
        "workplace.log",
    )
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = log_file
    sys.stderr = log_file
    try:
        server = WorkplaceHTTPServer((HOST, PORT), WorkplaceHandler)
    except OSError as exc:
        if _existing_server_is_jarvis():
            if show_hud:
                webbrowser.open(f"http://{HOST}:{PORT}/")
            return
        raise RuntimeError(
            f"Could not start the Workplace bridge on {HOST}:{PORT}: {exc}. "
            "Close any older Jarvis Workplace process and try again."
        ) from exc

    threading.Thread(
        target=_market_refresh_loop,
        name="jarvis-market",
        daemon=True,
    ).start()
    url = f"http://{HOST}:{PORT}/"
    print(f"Jarvis Workplace is running at {url}", flush=True)
    if show_hud:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Jarvis Workplace bridge.", flush=True)
    finally:
        server.server_close()


def _market_refresh_loop():
    while True:
        STATE.refresh_market()
        time.sleep(90)


if __name__ == "__main__":
    main()
