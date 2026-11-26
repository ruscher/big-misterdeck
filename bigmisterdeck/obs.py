"""OBS Studio over obs-websocket 5 (built into OBS 28+): source volumes, scenes, recording.

Standard library only: a minimal WebSocket client (RFC 6455) that keeps one
connection open, so each knob step costs one small message instead of a new
connection. When OBS is closed it fails at once and tries again every few
seconds, so the other knobs and buttons never wait for it.

Where to connect: ``OBS_WEBSOCKET_URL`` (``obsws://host:port/password``, the
same variable obs-cmd reads); without it, this computer's OBS on the port and
with the password OBS saved in its own settings.
"""

import base64
import hashlib
import json
import logging
import os
import select
import socket
import struct
import time
import urllib.parse

log = logging.getLogger("big-misterdeck")

OBS_SETTINGS = "~/.config/obs-studio/plugin_config/obs-websocket/config.json"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
AUTH_FAILED = 4009                  # obs-websocket close code

# Button actions: action -> (request type, config key, request field); no key = no argument.
BUTTONS = {
    "obs_scene": ("SetCurrentProgramScene", "scene", "sceneName"),
    "obs_mute": ("ToggleInputMute", "source", "inputName"),
    "obs_record": ("ToggleRecord", None, None),
    "obs_record_pause": ("ToggleRecordPause", None, None),
    "obs_stream": ("ToggleStream", None, None),
    "obs_virtual_camera": ("ToggleVirtualCam", None, None),
    "obs_replay_save": ("SaveReplayBuffer", None, None),
}

# Requests that must never run twice: if the connection drops after one was sent,
# OBS may already have done it, so it is reported as unsure instead of repeated
# (a repeated ToggleStream would go live and straight off air again).
NOT_REPEATABLE = {"ToggleRecord", "ToggleRecordPause", "ToggleStream", "ToggleVirtualCam", "ToggleInputMute",
                  "SaveReplayBuffer"}
DONE, FAILED, UNSURE = "done", "failed", "unsure"

# OBS's own mixer fader curve (libobs/obs-audio-controls.c, log fader), so the
# knob and the slider on screen sit at the same position for the same volume.
LOG_OFFSET_DB = 6.0
LOG_RANGE_DB = 96.0


def slider_db(percent):
    """Fader position 0-100 % -> dB (None = silence, -inf)."""
    position = max(0.0, min(100.0, float(percent))) / 100
    if position <= 0:
        return None
    if position >= 1:
        return 0.0
    span = LOG_RANGE_DB + LOG_OFFSET_DB
    return -span * (span / LOG_OFFSET_DB) ** -position + LOG_OFFSET_DB


def address(env=None, settings=OBS_SETTINGS):
    """(host, port, password) for OBS's WebSocket server; ValueError for a malformed OBS_WEBSOCKET_URL."""
    env = os.environ if env is None else env
    saved = {}
    try:
        with open(os.path.expanduser(settings), encoding="utf-8") as handle:
            saved = json.load(handle)
    except (OSError, ValueError):
        pass
    if not isinstance(saved, dict):
        saved = {}
    saved_password = saved.get("server_password") if saved.get("auth_required", True) else None
    url = env.get("OBS_WEBSOCKET_URL")
    if url:
        try:
            parts = urllib.parse.urlsplit(url)
            port = parts.port or 4455
        except ValueError as error:
            raise ValueError(f"OBS_WEBSOCKET_URL is not obsws://host:port/password: {error}") from None
        host = parts.hostname or "localhost"
        password = urllib.parse.unquote(parts.path.lstrip("/")) or None
        if password is None and host in ("localhost", "127.0.0.1", "::1"):
            password = saved_password
        return host, port, password
    try:
        port = int(saved.get("server_port") or 4455)
    except (TypeError, ValueError):
        port = 4455
    return "localhost", port, saved_password


class Closed(ConnectionError):
    def __init__(self, code, reason):
        super().__init__(f"OBS closed the connection ({code}{': ' + reason if reason else ''})")
        self.code = code


class Client:
    """One lazy, self-healing connection to OBS; every method answers False/None instead of raising."""

    def __init__(self, where=None, connect=socket.create_connection, clock=time.monotonic,
                 retry=3.0, timeout=1.0):
        self.where = where
        self.connect = connect
        self.clock = clock
        self.retry = retry
        self.timeout = timeout
        self._sock = None
        self._buf = b""
        self._next_try = 0.0
        self._seq = 0
        self._sent = False
        self._down_reported = False
        self._warned = set()

    # --- public ------------------------------------------------------------------------
    def set_volume(self, source, percent):
        """Put ``source``'s fader at ``percent`` (0-100) of its travel."""
        db = slider_db(percent)
        data = {"inputName": source}
        if db is None:
            data["inputVolumeMul"] = 0.0
        else:
            data["inputVolumeDb"] = round(db, 2)
        return self.request("SetInputVolume", data) is not None

    def press(self, action, button):
        """Run a button action from :data:`BUTTONS`: DONE, FAILED or UNSURE (OBS did not answer)."""
        kind, key, field = BUTTONS[action]
        return self._call(kind, {field: button[key]} if key else None, deliberate=True)[0]

    def request(self, kind, data=None):
        """Send one request; its responseData ({} when empty), or None when it failed."""
        outcome, answer = self._call(kind, data)
        return answer if outcome == DONE else None

    def _call(self, kind, data, deliberate=False):
        """(DONE | FAILED | UNSURE, responseData).

        ``deliberate`` (a button press, one act): connect now even inside the knobs'
        retry delay, and log the reason of every failure, not only the first.
        """
        for attempt in range(2):
            if not self._ensure(force=deliberate):
                return FAILED, None
            self._sent = False
            try:
                answer = self._exchange(kind, data)
                break
            except (OSError, ValueError) as error:
                self._drop(f"connection to OBS lost: {error}")
                if self._sent and kind in NOT_REPEATABLE:
                    log.warning("OBS did not answer %s: it may or may not have happened, look at OBS", kind)
                    return UNSURE, None
                if attempt == 0:
                    self._next_try = 0.0    # reconnect once, right away, and send it again
        else:
            return FAILED, None
        status = answer.get("requestStatus", {})
        name = (data or {}).get("inputName") or (data or {}).get("sceneName")
        problem = (kind, name, status.get("comment") or status.get("code"))
        if not status.get("result"):
            if deliberate or problem not in self._warned:    # a knob turn repeats it ~25 times a second
                self._warned.add(problem)
                log.warning("OBS %s %s: %s", kind, problem[1] or "", problem[2])
            return FAILED, None
        # this request works again: warn again if it breaks later; other sources keep their silence
        self._warned = {seen for seen in self._warned if seen[:2] != problem[:2]}
        return DONE, answer.get("responseData") or {}

    def connected(self):
        return self._ensure()

    def endpoint(self):
        """(host, port, password); ValueError when OBS_WEBSOCKET_URL is malformed."""
        return self.where or address()

    def _exchange(self, kind, data):
        self._seq += 1
        request_id = str(self._seq)
        self._send({"op": 6, "d": {"requestType": kind, "requestId": request_id, "requestData": data or {}}})
        self._sent = True
        while True:
            message = self._recv()
            if message.get("op") == 7 and message.get("d", {}).get("requestId") == request_id:
                return message["d"]

    def close(self):
        if self._sock:
            try:
                self._frame(0x8, struct.pack("!H", 1000))
            except OSError:
                pass
        self._drop(None)

    # --- connection --------------------------------------------------------------------
    def _ensure(self, force=False):
        if self._sock and self._closed_by_obs():
            # OBS quit or restarted since the last request: reconnect before sending anything,
            # so even a toggle that must not be repeated goes out on a live connection
            self._drop("connection to OBS lost: OBS closed it")
            self._next_try = 0.0
        if self._sock:
            return True
        if not force and self.clock() < self._next_try:
            return False
        try:
            host, port, password = self.endpoint()
        except ValueError as error:
            self._drop(str(error))          # reported once; the other knobs and buttons go on
            return False
        try:
            self._sock = self.connect((host, port), self.timeout)
            self._sock.settimeout(self.timeout)
            self._buf = b""
            self._handshake(host, port, password)
        except (OSError, ValueError, KeyError) as error:
            reason = error
            if isinstance(error, Closed) and error.code == AUTH_FAILED:
                reason = "wrong password (OBS_WEBSOCKET_URL or OBS's WebSocket settings)"
            self._drop(f"OBS not reachable on {host}:{port}: {reason}")
            return False
        log.info("connected to OBS on %s:%s", host, port)
        self._down_reported = False
        return True

    def _closed_by_obs(self):
        """True when the peer has closed the connection (end of stream waiting, nothing sent yet)."""
        try:
            ready, _, _ = select.select([self._sock], [], [], 0)
            return bool(ready) and self._sock.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    def _drop(self, why):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock, self._buf = None, b""
        self._next_try = self.clock() + self.retry
        if why and not self._down_reported:     # once per outage, not once per knob step
            log.warning("%s; trying again every %gs", why, self.retry)
            self._down_reported = True

    def _handshake(self, host, port, password):
        key = base64.b64encode(os.urandom(16)).decode()
        self._sock.sendall((f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                            "Sec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: obswebsocket.json\r\n\r\n")
                           .encode())
        while b"\r\n\r\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("no WebSocket answer")
            self._buf += chunk
        head, self._buf = self._buf.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        if " 101 " not in lines[0] + " ":
            raise ConnectionError(f"not a WebSocket server: {lines[0]}")
        headers = {name.strip().lower(): value.strip()
                   for name, _, value in (line.partition(":") for line in lines[1:])}
        expected = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        if headers.get("sec-websocket-accept") != expected:
            raise ConnectionError("bad WebSocket handshake")

        hello = self._recv()
        if hello.get("op") != 0:
            raise ConnectionError("OBS did not say hello")
        identify = {"rpcVersion": 1, "eventSubscriptions": 0}
        challenge = hello["d"].get("authentication")
        if challenge:
            if not password:
                raise ConnectionError("OBS asks for a password: set OBS_WEBSOCKET_URL=obsws://host:port/password")
            identify["authentication"] = auth_string(password, challenge["salt"], challenge["challenge"])
        self._send({"op": 1, "d": identify})
        if self._recv().get("op") != 2:
            raise ConnectionError("OBS did not accept the identification")

    # --- frames ------------------------------------------------------------------------
    def _send(self, message):
        self._frame(0x1, json.dumps(message).encode())

    def _frame(self, opcode, payload):
        size = len(payload)
        if size < 126:
            head = struct.pack("!BB", 0x80 | opcode, 0x80 | size)
        elif size < 1 << 16:
            head = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, size)
        else:
            head = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, size)
        mask = os.urandom(4)
        self._sock.sendall(head + mask + _xor(payload, mask))

    def _read(self, size):
        while len(self._buf) < size:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("OBS closed the connection")
            self._buf += chunk
        data, self._buf = self._buf[:size], self._buf[size:]
        return data

    def _recv(self):
        """The next JSON message (pings answered, fragments joined)."""
        message = b""
        while True:
            first, second = self._read(2)
            opcode, size = first & 0x0F, second & 0x7F
            if size == 126:
                size = struct.unpack("!H", self._read(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self._read(8))[0]
            mask = self._read(4) if second & 0x80 else None
            payload = self._read(size)
            if mask:
                payload = _xor(payload, mask)
            if opcode == 0x8:
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else None
                raise Closed(code, payload[2:].decode("utf-8", errors="replace"))
            if opcode == 0x9:
                self._frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            message += payload
            if first & 0x80:
                return json.loads(message)


def auth_string(password, salt, challenge):
    """obs-websocket 5 authentication: base64(sha256(base64(sha256(password + salt)) + challenge))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest())
    return base64.b64encode(hashlib.sha256(secret + challenge.encode()).digest()).decode()


def _xor(data, mask):
    return bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
