import hmac
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

class PlaybackBridge:
    STATES = {"playing", "paused", "loading", "buffering", "seeking", "ended", "suspended", "failed"}
    
    def __init__(self, streamer, token, cooldown_seconds = 90, max_reopens = 3):
        if not isinstance(token, str) or len(token) < 32:
            raise ValueError("bridge.token must be a random secret of at least 32 characters")
        if cooldown_seconds <= 0 or max_reopens < 0:
            raise ValueError("Invalid bridge recovery limits")
        self.streamer = streamer
        self.token = token
        self.cooldown = cooldown_seconds
        self.max_reopens = max_reopens
        self.lock = threading.Lock()
        self.instance_id = None
        self.stream_id = None
        self.state = None
        self.report_at = 0
        self.opened_at = 0
        self.reopens = 0
        self.server = None
        self.thread = None

    def getTabToken(self, instance_id):
        return hmac.new(self.token.encode("utf-8"), instance_id.encode("ascii"), "sha256").hexdigest()

    def recordOpen(self, instance_id, stream_id, recovery = False):
        with self.lock:
            self.instance_id = instance_id
            self.stream_id = stream_id
            self.state = None
            self.report_at = 0
            self.opened_at = time.monotonic()
            self.reopens = self.reopens + 1 if recovery else 0

    def report(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        instance_id = payload.get("instance_id")
        state = payload.get("state")
        if payload.get("streamer") != self.streamer or not isinstance(instance_id, str) or not re.fullmatch(r"[0-9a-f]{32}", instance_id) or not isinstance(state, str) or state not in self.STATES:
            raise ValueError("Invalid playback report")
        with self.lock:
            if instance_id != self.instance_id:
                return False
            self.state = state
            self.report_at = time.monotonic()
            return True

    def recoveryDue(self):
        with self.lock:
            now = time.monotonic()
            return self.state == "failed" and now - self.report_at <= 30 and now - self.opened_at >= self.cooldown and self.reopens < self.max_reopens

    def getStatus(self):
        with self.lock:
            if self.state is None or time.monotonic() - self.report_at > 30:
                return "no recent report"
            if self.state == "failed" and self.reopens >= self.max_reopens:
                return "failed; recovery limit reached"
            return self.state

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout = 5)

def startTamperMonkey(streamer, token, port = 8765, cooldown_seconds = 90, max_reopens = 3):
    bridge = PlaybackBridge(streamer, token, cooldown_seconds, max_reopens)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(3)

        def log_message(self, *_):
            pass

        def reply(self, status, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/status":
                self.reply(404, {"error": "Not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("Invalid request length")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Expected an object")
                instance_id = payload.get("instance_id")
                if not isinstance(instance_id, str) or not re.fullmatch(r"[0-9a-f]{32}", instance_id):
                    raise ValueError("Invalid instance ID")
                supplied = self.headers.get("Authorization", "").encode("utf-8")
                expected = ("Bearer " + bridge.getTabToken(instance_id)).encode("utf-8")
                if not hmac.compare_digest(supplied, expected):
                    self.reply(401, {"error": "Unauthorized"})
                    return
                accepted = bridge.report(payload)
            except (ValueError, OSError):
                self.reply(400, {"error": "Invalid playback report"})
                return
            self.reply(200, {"accepted": accepted})

    bridge.server = HTTPServer(("127.0.0.1", port), Handler)
    bridge.thread = threading.Thread(target = bridge.server.serve_forever, daemon = True)
    bridge.thread.start()
    return bridge