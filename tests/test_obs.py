"""OBS over obs-websocket 5: a fake OBS on the other end of a socket pair checks the
handshake, the password, the frames and the volume requests."""

import base64
import hashlib
import json
import logging
import socket
import struct
import threading

import pytest

from bigmisterdeck import actions, cli, config, daemon, midi, obs


# --- a fake OBS ----------------------------------------------------------------------------
class FakeObs:
    def __init__(self, password="s3cret", sources=("Mic Principal",), scenes=("Camera", "Screen"), ping=False):
        self.password = password
        self.sources = set(sources)
        self.scenes = list(scenes)
        self.ping = ping
        self.requests = []
        self.identified = threading.Event()
        self.server_ends = []

    def connect(self, where, timeout):
        client, server = socket.socketpair()
        self.server_ends.append(server)
        threading.Thread(target=self.serve, args=(server,), daemon=True).start()
        return client

    # frames (server side: unmasked out, masked in)
    def read(self, sock, size):
        data = b""
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError
            data += chunk
        return data

    def recv(self, sock):
        first, second = self.read(sock, 2)
        size = second & 0x7F
        if size == 126:
            size = struct.unpack("!H", self.read(sock, 2))[0]
        mask = self.read(sock, 4)
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(self.read(sock, size)))
        return first & 0x0F, payload

    def send(self, sock, message, opcode=0x1):
        payload = message if isinstance(message, bytes) else json.dumps(message).encode()
        size = len(payload)
        head = (struct.pack("!BB", 0x80 | opcode, size) if size < 126
                else struct.pack("!BBH", 0x80 | opcode, 126, size))
        sock.sendall(head + payload)

    def serve(self, sock):
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                head += sock.recv(1024)
            key = next(line.split(":", 1)[1].strip() for line in head.decode().split("\r\n")
                       if line.lower().startswith("sec-websocket-key"))
            accept = base64.b64encode(hashlib.sha1((key + obs.WS_GUID).encode()).digest()).decode()
            sock.sendall(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                         f"Sec-WebSocket-Accept: {accept}\r\n\r\n".encode())
            hello = {"obsWebSocketVersion": "5.7.6", "rpcVersion": 1}
            if self.password:
                hello["authentication"] = {"challenge": "chal", "salt": "salt"}
            self.send(sock, {"op": 0, "d": hello})
            _, payload = self.recv(sock)
            identify = json.loads(payload)["d"]
            if self.password and identify.get("authentication") != obs.auth_string(self.password, "salt", "chal"):
                self.send(sock, struct.pack("!H", obs.AUTH_FAILED) + b"Authentication failed.", opcode=0x8)
                return
            self.send(sock, {"op": 2, "d": {"negotiatedRpcVersion": 1}})
            self.identified.set()
            while True:
                opcode, payload = self.recv(sock)
                if opcode == 0x8:
                    return
                if opcode != 0x1:
                    continue
                d = json.loads(payload)["d"]
                self.requests.append((d["requestType"], d["requestData"]))
                if self.ping:
                    self.send(sock, b"hi", opcode=0x9)
                data, answer = d["requestData"], {}
                if d["requestType"] == "GetSceneList":
                    found, answer = True, {"scenes": [{"sceneName": name} for name in self.scenes]}
                elif "sceneName" in data:
                    found = data["sceneName"] in self.scenes
                else:
                    found = data.get("inputName", "Mic Principal") in self.sources
                reply = {"requestType": d["requestType"], "requestId": d["requestId"],
                         "requestStatus": {"result": found, "code": 100 if found else 600,
                                           **({} if found else {"comment": "No source"})}}
                if answer:
                    reply["responseData"] = answer
                self.send(sock, {"op": 7, "d": reply})
        except (ConnectionError, OSError):
            pass
        finally:
            sock.close()

    def drop_all(self):
        for end in self.server_ends:
            end.shutdown(socket.SHUT_RDWR)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


CLIENTS = []


@pytest.fixture(autouse=True)
def close_clients():
    yield
    while CLIENTS:
        CLIENTS.pop().close()


def client_for(fake, clock=None, **kw):
    client = obs.Client(where=("localhost", 4455, kw.pop("password", "s3cret")), connect=fake.connect,
                        clock=clock or Clock(), **kw)
    CLIENTS.append(client)
    return client


# --- the fader curve and the address -----------------------------------------------------------
def test_slider_matches_obs_log_fader():
    assert obs.slider_db(0) is None
    assert obs.slider_db(100) == 0.0
    assert obs.slider_db(150) == 0.0
    assert obs.slider_db(50) == pytest.approx(-18.74, abs=0.01)
    assert obs.slider_db(1) == pytest.approx(-93.15, abs=0.01)
    values = [obs.slider_db(p) for p in range(1, 101)]
    assert values == sorted(values)


def test_address_from_url_or_from_obs_own_settings(tmp_path):
    settings = tmp_path / "config.json"
    settings.write_text(json.dumps({"server_port": 4460, "auth_required": True, "server_password": "fromobs"}))
    assert obs.address({"OBS_WEBSOCKET_URL": "obsws://studio:4499/p%40ss"}, settings) == ("studio", 4499, "p@ss")
    assert obs.address({"OBS_WEBSOCKET_URL": "obsws://localhost:4455"}, settings) == ("localhost", 4455, "fromobs")
    assert obs.address({}, settings) == ("localhost", 4460, "fromobs")
    settings.write_text(json.dumps({"auth_required": False, "server_password": "unused"}))
    assert obs.address({}, settings) == ("localhost", 4455, None)
    assert obs.address({}, tmp_path / "missing.json") == ("localhost", 4455, None)


def test_auth_string_is_the_obs_websocket_recipe():
    # the protocol document's recipe, step by step: sha256(password + salt), base64, + challenge, sha256, base64
    secret = base64.b64encode(hashlib.sha256(b"supersecretpassword" + b"lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI=")
                              .digest())
    expected = base64.b64encode(hashlib.sha256(secret + b"+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY=").digest())
    assert obs.auth_string("supersecretpassword", "lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI=",
                           "+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY=") == expected.decode()


# --- talking to OBS ------------------------------------------------------------------------------
def test_volume_requests_over_one_connection_with_password_and_pings():
    fake = FakeObs(ping=True)
    client = client_for(fake)
    assert client.set_volume("Mic Principal", 50)
    assert client.set_volume("Mic Principal", 0)
    assert client.set_volume("Mic Principal", 100)
    assert len(fake.server_ends) == 1                  # one connection for every step
    assert fake.requests == [
        ("SetInputVolume", {"inputName": "Mic Principal", "inputVolumeDb": -18.74}),
        ("SetInputVolume", {"inputName": "Mic Principal", "inputVolumeMul": 0.0}),
        ("SetInputVolume", {"inputName": "Mic Principal", "inputVolumeDb": 0.0}),
    ]
    client.close()


def test_unknown_source_is_warned_once_not_on_every_step(caplog):
    fake = FakeObs()
    client = client_for(fake)
    with caplog.at_level(logging.WARNING, "big-misterdeck"):
        for percent in range(10):
            assert not client.set_volume("Nope", percent)
    assert len([r for r in caplog.records if "Nope" in r.getMessage()]) == 1
    assert client.set_volume("Mic Principal", 10)       # the connection survived the errors


def test_two_knobs_one_good_one_misnamed_still_warn_once(caplog):
    client = client_for(FakeObs())
    with caplog.at_level(logging.WARNING, "big-misterdeck"):
        for percent in range(10):                       # both knobs turned together
            assert client.set_volume("Mic Principal", percent)
            assert not client.set_volume("Nope", percent)
    assert len([r for r in caplog.records if "Nope" in r.getMessage()]) == 1


def test_malformed_url_is_reported_not_raised(caplog, monkeypatch, capsys):
    monkeypatch.setenv("OBS_WEBSOCKET_URL", "obsws://localhost:port/secret")
    with pytest.raises(ValueError, match="OBS_WEBSOCKET_URL"):
        obs.address()
    client = obs.Client(connect=FakeObs().connect, clock=Clock())
    CLIENTS.append(client)
    with caplog.at_level(logging.WARNING, "big-misterdeck"):
        assert not client.set_volume("Mic Principal", 50)   # the daemon goes on
        assert not client.set_volume("Mic Principal", 60)
    assert caplog.text.count("OBS_WEBSOCKET_URL") == 1
    cfg = config.validate(config._merge(config.DEFAULTS, {"knobs": {"18": {"action": "obs_volume",
                                                                           "source": "Mic Principal"}}}))
    assert not cli.check_obs(cfg, client)
    assert "!!  obs        OBS_WEBSOCKET_URL" in capsys.readouterr().out


def test_wrong_password_is_reported_and_retried_later(caplog):
    clock = Clock()
    fake = FakeObs(password="right")
    client = client_for(fake, clock, password="wrong")
    with caplog.at_level(logging.WARNING, "big-misterdeck"):
        assert not client.set_volume("Mic Principal", 50)
        assert not client.set_volume("Mic Principal", 60)     # within the retry delay: no new attempt
    assert len(fake.server_ends) == 1
    assert "wrong password" in caplog.text


def test_obs_closed_fails_fast_and_reconnects_when_it_opens():
    clock = Clock()
    fake = FakeObs()
    state = {"open": False}

    def connect(where, timeout):
        if not state["open"]:
            raise ConnectionRefusedError(111, "Connection refused")
        return fake.connect(where, timeout)

    client = obs.Client(where=("localhost", 4455, "s3cret"), connect=connect, clock=clock, retry=3)
    CLIENTS.append(client)
    assert not client.set_volume("Mic Principal", 50)
    state["open"] = True
    assert not client.set_volume("Mic Principal", 50)         # still waiting for the retry delay
    clock.now += 3
    assert client.set_volume("Mic Principal", 50)


def test_obs_restarted_reconnects_at_once_on_the_next_step():
    fake = FakeObs()
    client = client_for(fake)
    assert client.set_volume("Mic Principal", 50)
    fake.drop_all()                                            # OBS quit and came back
    assert client.set_volume("Mic Principal", 60)
    assert len(fake.server_ends) == 2


# --- configuration, deck and --check ------------------------------------------------------------
def test_obs_volume_needs_a_source(tmp_path):
    file = tmp_path / "config.toml"
    file.write_text('[knobs.18]\naction = "obs_volume"\n')
    with pytest.raises(config.ConfigError, match="obs_volume needs source"):
        config.load(str(file))
    file.write_text('[knobs.18]\naction = "obs_volume"\nsource = "Mic Principal"\n')
    assert config.load(str(file))["knobs"][18] == {"action": "obs_volume", "source": "Mic Principal"}


class RecordingObs:
    def __init__(self):
        self.calls = []

    def set_volume(self, source, percent):
        self.calls.append((source, percent))
        return True


def test_obs_knob_uses_the_whole_travel_whatever_max_volume(tmp_path):
    file = tmp_path / "config.toml"
    file.write_text('[behaviour]\nmax_volume = 150\n[knobs.18]\naction = "obs_volume"\nsource = "Mic Principal"\n')
    cfg = config.load(str(file))
    clock, fake_obs = Clock(), RecordingObs()
    deck = daemon.Deck(cfg, audio=None, clock=clock, obs=fake_obs)
    deck.handle(midi.Event(midi.CONTROL, 0, 18, 127))
    clock.now += 1
    deck.handle(midi.Event(midi.CONTROL, 0, 18, 64))
    assert fake_obs.calls == [("Mic Principal", 100), ("Mic Principal", 50)]


def test_turn_without_an_obs_client_does_nothing():
    assert actions.turn({"action": "obs_volume", "source": "x"}, 50, audio=None) == "obs_volume"


def test_check_reports_obs_and_missing_sources(tmp_path, capsys):
    file = tmp_path / "config.toml"
    file.write_text('[knobs.18]\naction = "obs_volume"\nsource = "Mic Principal"\n'
                    '[knobs.19]\naction = "obs_volume"\nsource = "Typo"\n')
    cfg = config.load(str(file))
    assert not cli.check_obs(cfg, client_for(FakeObs()))
    out = capsys.readouterr().out
    assert "OK  obs source 'Mic Principal'" in out and "!!  obs source 'Typo' not found" in out
    assert cli.check_obs(config.load("/nonexistent"))           # no OBS knob: nothing to check


# --- buttons ------------------------------------------------------------------------------------
@pytest.mark.parametrize("button, sent", [
    ({"action": "obs_scene", "scene": "Camera"}, ("SetCurrentProgramScene", {"sceneName": "Camera"})),
    ({"action": "obs_mute", "source": "Mic Principal"}, ("ToggleInputMute", {"inputName": "Mic Principal"})),
    ({"action": "obs_record"}, ("ToggleRecord", {})),
    ({"action": "obs_record_pause"}, ("ToggleRecordPause", {})),
    ({"action": "obs_stream"}, ("ToggleStream", {})),
    ({"action": "obs_virtual_camera"}, ("ToggleVirtualCam", {})),
    ({"action": "obs_replay_save"}, ("SaveReplayBuffer", {})),
])
def test_obs_buttons_send_their_request(button, sent):
    fake = FakeObs()
    client = client_for(fake)
    done = actions.press(button, audio=None, behaviour={}, obs=client)
    assert fake.requests == [sent]
    assert done == button["action"] + (f" {(button.get('scene') or button.get('source'))!r}"
                                       if len(button) > 1 else "")


def test_a_misnamed_scene_is_reported_in_the_log_line():
    client = client_for(FakeObs())
    assert actions.press({"action": "obs_scene", "scene": "Typo"}, None, {}, obs=client) == "obs_scene 'Typo' failed"


def test_a_button_tries_obs_at_once_even_inside_the_knob_retry_delay():
    clock, fake, state = Clock(), FakeObs(), {"open": False}

    def connect(where, timeout):
        if not state["open"]:
            raise ConnectionRefusedError(111, "Connection refused")
        return fake.connect(where, timeout)

    client = obs.Client(where=("localhost", 4455, "s3cret"), connect=connect, clock=clock, retry=3)
    CLIENTS.append(client)
    assert not client.set_volume("Mic Principal", 50)          # OBS closed: the knobs wait 3 s
    state["open"] = True                                        # the user opens OBS and presses a button
    assert client.press("obs_record", {"action": "obs_record"})
    assert fake.requests == [("ToggleRecord", {})]


def test_obs_buttons_need_their_name(tmp_path):
    file = tmp_path / "config.toml"
    file.write_text('[buttons.8]\naction = "obs_scene"\n[buttons.9]\naction = "obs_mute"\nsource = " "\n')
    with pytest.raises(config.ConfigError) as error:
        config.load(str(file))
    assert "obs_scene needs scene" in str(error.value) and "obs_mute needs source" in str(error.value)
    file.write_text('[buttons.8]\naction = "obs_scene"\nscene = "Camera"\n[buttons.9]\naction = "obs_stream"\n')
    assert config.load(str(file))["buttons"][8] == {"action": "obs_scene", "scene": "Camera"}


def test_deck_sends_obs_buttons_to_the_client(caplog):
    class Pressed:
        def __init__(self):
            self.calls = []

        def press(self, action, button):
            self.calls.append(action)
            return True

    cfg = config.validate(config._merge(config.DEFAULTS, {"buttons": {"6": {"action": "obs_record"}}}))
    pressed = Pressed()
    deck = daemon.Deck(cfg, audio=None, clock=Clock(), obs=pressed)
    with caplog.at_level(logging.INFO, "big-misterdeck"):
        deck.handle(midi.Event(midi.NOTE_ON, 0, 6, 127))
    assert pressed.calls == ["obs_record"] and "button 6: obs_record" in caplog.text


def test_check_reports_scenes_and_mute_sources(capsys):
    cfg = config.validate(config._merge(config.DEFAULTS, {"buttons": {
        "8": {"action": "obs_scene", "scene": "Camera"},
        "9": {"action": "obs_scene", "scene": "Typo"},
        "10": {"action": "obs_mute", "source": "Mic Principal"},
    }}))
    assert not cli.check_obs(cfg, client_for(FakeObs()))
    out = capsys.readouterr().out
    assert "OK  obs scene  'Camera'" in out and "!!  obs scene  'Typo' not found" in out
    assert "OK  obs source 'Mic Principal'" in out
