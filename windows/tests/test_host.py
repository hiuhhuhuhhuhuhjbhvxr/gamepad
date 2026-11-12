"""End-to-end tests: start host.py in simulation mode and talk to it like a phone does."""
import base64, json, os, socket, subprocess, sys, tempfile, time, unittest, urllib.request
from pathlib import Path

HOST = Path(__file__).resolve().parent.parent / "host.py"
PORT = 18090

def frame(text):
    d = text.encode(); m = os.urandom(4)
    return bytes([0x81, 0x80 | len(d)]) + m + bytes(c ^ m[i % 4] for i, c in enumerate(d))

def read_frame(s):
    h = s.recv(2); n = h[1] & 0x7F
    return s.recv(n).decode()

def ws_connect(pin):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=3)
    key = base64.b64encode(os.urandom(16)).decode()
    s.send(f"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
    assert b"101" in s.recv(1024)
    s.send(frame("H" + pin))
    return s, read_frame(s)

class HostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.log = open(os.path.join(cls.tmp, "out.log"), "w")
        env = dict(os.environ, APPDATA=cls.tmp, HOME=cls.tmp, USERPROFILE=cls.tmp)
        cls.proc = subprocess.Popen([sys.executable, str(HOST), "--sim", "--no-browser", "--port", str(PORT)],
                                    stdout=cls.log, stderr=subprocess.STDOUT, env=env)
        for _ in range(50):
            try:
                cls.status = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/status"))
                break
            except Exception:
                time.sleep(0.1)
        cls.pin = cls.status["pin"]

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate(); cls.proc.wait(5); cls.log.close()

    def output(self):
        return Path(self.tmp, "out.log").read_text()

    def test_1_status_and_page(self):
        self.assertEqual(self.status["mode"], "keyboard")
        self.assertEqual(self.status["max"], 1)
        self.assertEqual(len(self.pin), 4)
        html = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/").read().decode()
        self.assertIn("Game Pad Remote", html)

    def test_2_wrong_pin(self):
        s, r = ws_connect("0000" if self.pin != "0000" else "1111")
        self.assertEqual(r, "BAD"); s.close()

    def test_3_keys_and_single_phone(self):
        s, r = ws_connect(self.pin)
        self.assertEqual(r, "OK 1")
        s2, r2 = ws_connect(self.pin)
        self.assertEqual(r2, "FULL"); s2.close()
        # A + RT, left stick up/left, right stick right
        s.send(frame("S 1 0 255 -30000 30000 32767 0")); time.sleep(0.25)
        s.send(frame("S 0 0 0 0 0 0 0")); time.sleep(0.1)
        s.close(); time.sleep(0.4)
        out = self.output()
        for line in ("key SPACE down", "mouse MOUSE_LEFT down", "key W down", "key A down",
                     "key SPACE up", "mouse MOUSE_LEFT up", "key W up", "key A up"):
            self.assertIn(line, out)
        self.assertIn("mouse move", out)

    def test_4_keys_released_on_dropped_connection(self):
        s, r = ws_connect(self.pin); self.assertEqual(r, "OK 1")
        s.send(frame("S 2 0 0 0 0 0 0")); time.sleep(0.15)   # B = LCTRL held
        s.close(); time.sleep(0.4)                           # phone vanishes while holding B
        self.assertIn("key LCTRL up", self.output())

    def test_5_discovery(self):
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.settimeout(2)
        u.sendto(b"RGDISCOVER", ("127.0.0.1", 26761))
        data, _ = u.recvfrom(256)
        self.assertTrue(data.decode().startswith(f"RGHOST|{PORT}|"))

    def test_6_second_instance_detected(self):
        r = subprocess.run([sys.executable, str(HOST), "--sim", "--no-browser", "--port", str(PORT)],
                           capture_output=True, text=True, timeout=15,
                           env=dict(os.environ, APPDATA=self.tmp, HOME=self.tmp))
        self.assertIn("Already running", r.stdout)

if __name__ == "__main__":
    unittest.main(verbosity=2)
