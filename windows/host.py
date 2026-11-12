#!/usr/bin/env python3
"""
Game Pad Remote - PC host  (single file, only dependency: vgamepad)

Run:   python host.py
Phone: open  http://<PC-IP>:8080  in the phone browser, enter the PIN.
PC:    the same page opens at http://localhost:8080 (host console + same gamepad GUI).

DEFAULT "free mode": no driver. The phone gamepad is turned into keyboard keys + mouse movement
(SendInput), remappable in  %APPDATA%\\RemoteGamepad\\keymap.json .
The Android app finds this PC by UDP broadcast (port 26761) and then opens the same web page.
Optional  --mode xbox  gives a virtual Xbox 360 pad (needs the ViGEmBus driver + vgamepad).
Wi-Fi / Ethernet / USB-tethering / Bluetooth-tethering all work because the transport is plain
IP (HTTP + WebSocket) on one TCP port.

Wire protocol (WebSocket text frames, path /ws):
  client -> "H<pin>"                                   server -> "OK <padNumber>" | "BAD" | "FULL"
  client -> "S <buttons> <lt> <rt> <lx> <ly> <rx> <ry>"   (ints; sticks -32768..32767, triggers 0..255)
  server -> "V <large> <small>"                        rumble (0..255)
buttons bits: 0 A,1 B,2 X,3 Y,4 LB,5 RB,6 Back,7 Start,8 L3,9 R3,10 Up,11 Down,12 Left,13 Right,14 Guide
"""
import argparse, base64, hashlib, json, os, random, socket, struct, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
WEB = BASE / "web"
MAX_PADS = 4
VERSION = "1.1.0"
DISCOVERY_PORT = 26761
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
BTN_NAMES = ["A", "B", "X", "Y", "LEFT_SHOULDER", "RIGHT_SHOULDER", "BACK", "START",
             "LEFT_THUMB", "RIGHT_THUMB", "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT", "GUIDE"]

# ----------------------------------------------------------------------------- config / helpers
def cfg_dir() -> Path:
    d = Path(os.environ.get("APPDATA") or Path.home()) / "RemoteGamepad"
    d.mkdir(parents=True, exist_ok=True)
    return d

def load_pin() -> str:
    f = cfg_dir() / "pin.txt"
    try:
        p = f.read_text().strip()
        if len(p) == 4 and p.isdigit():
            return p
    except OSError:
        pass
    p = f"{random.randint(0, 9999):04d}"
    try:
        f.write_text(p)
    except OSError:
        pass
    return p

def local_ips():
    ips = []
    try:  # primary outbound interface (no packet is sent)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1)); ips.append(s.getsockname()[0]); s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    except OSError:
        pass
    out = []
    for ip in ips:
        if ip.startswith(("127.", "169.254.")) or ip in out:
            continue
        out.append(ip)
    return out

def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


# ----------------------------------------------------------------------------- ViGEmBus driver installer
VIGEM_URL = "https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/ViGEmBus_1.22.0_x64_x86_arm64.exe"

def vigem_installed() -> bool:
    if os.name != "nt":
        return True
    import subprocess
    try:
        r = subprocess.run(["sc", "query", "ViGEmBus"], capture_output=True, text=True,
                           creationflags=0x08000000)
        return r.returncode == 0
    except Exception:
        return False

def _msgbox(text, title="Game Pad Remote", yesno=False):
    import ctypes
    flags = (0x24 if yesno else 0x40) | 0x10000   # YESNO+QUESTION / INFO, foreground
    return ctypes.windll.user32.MessageBoxW(0, text, title, flags)  # 6 = Yes

def ensure_vigem():
    """Own driver prompt: offer to install ViGEmBus (virtual Xbox 360 controller driver)."""
    if vigem_installed():
        return
    msg = ("Game Pad Remote needs the free \"ViGEmBus\" driver to create a virtual Xbox 360 controller.\n\n"
           "Install it now? (Windows will ask for administrator permission.)")
    if _msgbox(msg, yesno=True) != 6:
        sys.exit("ViGEmBus driver is required. Run again and choose Yes, or use --sim.")
    import subprocess, tempfile, urllib.request
    local = BASE / "ViGEmBus_Setup.exe"            # bundled copy (offline / packaged exe)
    exe = str(local) if local.exists() else None
    if exe is None:
        exe = os.path.join(tempfile.gettempdir(), "ViGEmBus_Setup.exe")
        print("Downloading ViGEmBus driver...", flush=True)
        try:
            req = urllib.request.Request(VIGEM_URL, headers={"User-Agent": "GamePadRemote"})
            with urllib.request.urlopen(req, timeout=60) as r, open(exe, "wb") as f:
                f.write(r.read())
            if os.path.getsize(exe) < 500_000:
                raise OSError("download incomplete")
        except Exception as e:
            _msgbox(f"Could not download the driver:\n{e}\n\nDownload it manually from:\n"
                    "https://github.com/nefarius/ViGEmBus/releases\nthen run this app again.")
            sys.exit(1)
    print("Installing ViGEmBus driver (approve the administrator prompt)...", flush=True)
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Start-Process -FilePath '{exe}' -ArgumentList '/quiet','/norestart' -Verb RunAs -Wait"],
                   creationflags=0x08000000)
    if vigem_installed():
        _msgbox("Driver installed. Starting Game Pad Remote.")
    else:
        _msgbox("The driver was not installed (permission denied or a restart is needed).\n"
                "Restart Windows and run the app again, or install ViGEmBus manually.")
        sys.exit(1)


# ----------------------------------------------------------------------------- free mode: keyboard + mouse
DEFAULT_CFG = {
    "mouse_speed": 1200,          # pixels/second at full right-stick deflection
    "mouse_deadzone": 0.12,
    "invert_mouse_y": False,
    "stick_threshold": 0.35,      # left stick -> WASD digital threshold
    "keys": {
        "LS_UP": "W", "LS_DOWN": "S", "LS_LEFT": "A", "LS_RIGHT": "D",
        "A": "SPACE", "B": "LCTRL", "X": "R", "Y": "F", "LB": "Q", "RB": "E",
        "LT": "MOUSE_RIGHT", "RT": "MOUSE_LEFT", "L3": "LSHIFT", "R3": "C",
        "BACK": "TAB", "START": "ESC", "GUIDE": "M",
        "UP": "UP", "DOWN": "DOWN", "LEFT": "LEFT", "RIGHT": "RIGHT",
    },
}
CFG = json.loads(json.dumps(DEFAULT_CFG))

def keymap_path() -> Path:
    return cfg_dir() / "keymap.json"

def load_cfg():
    f = keymap_path()
    if f.exists():
        try:
            u = json.loads(f.read_text(encoding="utf-8"))
            CFG["keys"].update({k: str(v).upper() for k, v in u.get("keys", {}).items()})
            for k in ("mouse_speed", "mouse_deadzone", "invert_mouse_y", "stick_threshold"):
                if k in u:
                    CFG[k] = u[k]
        except Exception as e:
            print("keymap.json ignored (bad JSON):", e)
    else:
        try:
            f.write_text(json.dumps(DEFAULT_CFG, indent=2), encoding="utf-8")
        except OSError:
            pass

# scan codes (set 1); (code, extended)
SCAN = {"ESC": (1, 0), "TAB": (0x0F, 0), "ENTER": (0x1C, 0), "SPACE": (0x39, 0), "BACKSPACE": (0x0E, 0),
        "LCTRL": (0x1D, 0), "LSHIFT": (0x2A, 0), "LALT": (0x38, 0), "RSHIFT": (0x36, 0),
        "UP": (0x48, 1), "DOWN": (0x50, 1), "LEFT": (0x4B, 1), "RIGHT": (0x4D, 1),
        "HOME": (0x47, 1), "END": (0x4F, 1), "PAGEUP": (0x49, 1), "PAGEDOWN": (0x51, 1),
        "INSERT": (0x52, 1), "DELETE": (0x53, 1)}
for _row, _start in (("QWERTYUIOP", 0x10), ("ASDFGHJKL", 0x1E), ("ZXCVBNM", 0x2C), ("1234567890", 0x02)):
    for _i, _c in enumerate(_row):
        SCAN[_c] = (_start + _i, 0)
for _i in range(1, 13):
    SCAN[f"F{_i}"] = ((0x3A + _i) if _i <= 10 else (0x57 + _i - 11), 0)
MOUSE_BTN = {"MOUSE_LEFT": (0x02, 0x04), "MOUSE_RIGHT": (0x08, 0x10), "MOUSE_MIDDLE": (0x20, 0x40)}

SIM = False
if os.name == "nt":
    import ctypes
    from ctypes import wintypes
    class _KI(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
    class _MI(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
    class _U(ctypes.Union):
        _fields_ = [("ki", _KI), ("mi", _MI)]
    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]
    def _send(inp):
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

def inject_key(name, down):
    if name in MOUSE_BTN:
        flag = MOUSE_BTN[name][0 if down else 1]
        if SIM or os.name != "nt":
            return print(f"[sim] mouse {name} {'down' if down else 'up'}", flush=True)
        i = _INPUT(type=0); i.u.mi = _MI(0, 0, 0, flag, 0, 0); return _send(i)
    if name not in SCAN:
        return
    code, ext = SCAN[name]
    if SIM or os.name != "nt":
        return print(f"[sim] key {name} {'down' if down else 'up'}", flush=True)
    flags = 0x8 | (0x1 if ext else 0) | (0 if down else 0x2)
    i = _INPUT(type=1); i.u.ki = _KI(0, code, flags, 0, 0); _send(i)

def inject_mouse_move(dx, dy):
    if SIM or os.name != "nt":
        return print(f"[sim] mouse move {dx},{dy}", flush=True)
    i = _INPUT(type=0); i.u.mi = _MI(dx, dy, 0, 0x1, 0, 0); _send(i)

BTN_ACTIONS = ["A", "B", "X", "Y", "LB", "RB", "BACK", "START", "L3", "R3", "UP", "DOWN", "LEFT", "RIGHT", "GUIDE"]

class InputPad:
    """Phone gamepad -> keyboard keys + mouse movement. Releases everything on close."""
    def __init__(self):
        self.down, self.rx, self.ry, self.alive = set(), 0.0, 0.0, True
        threading.Thread(target=self._mouse_loop, daemon=True).start()

    def _sync(self, want):
        for k in self.down - want:
            inject_key(k, False)
        for k in want - self.down:
            inject_key(k, True)
        self.down = want

    def apply(self, b, lt, rt, lx, ly, rx, ry):
        km = CFG["keys"]; want = set()
        for i, n in enumerate(BTN_ACTIONS):
            if (b >> i) & 1:
                want.add(km.get(n, ""))
        if lt > 127: want.add(km.get("LT", ""))
        if rt > 127: want.add(km.get("RT", ""))
        th = CFG["stick_threshold"] * 32767
        if ly > th: want.add(km.get("LS_UP", ""))
        if ly < -th: want.add(km.get("LS_DOWN", ""))
        if lx < -th: want.add(km.get("LS_LEFT", ""))
        if lx > th: want.add(km.get("LS_RIGHT", ""))
        want.discard("")
        self._sync(want)
        self.rx, self.ry = rx / 32767.0, ry / 32767.0

    def _curve(self, v):
        dz = CFG["mouse_deadzone"]; a = abs(v)
        if a < dz:
            return 0.0
        a = (a - dz) / (1 - dz)
        a = 0.5 * a + 0.5 * a * a * a        # fine control near centre, fast at the edge
        return a if v > 0 else -a

    def _mouse_loop(self):
        ax = ay = 0.0; t = time.perf_counter()
        while self.alive:
            time.sleep(0.008)
            n = time.perf_counter(); dt, t = n - t, n
            sp = CFG["mouse_speed"]
            ax += self._curve(self.rx) * sp * dt
            ay += self._curve(self.ry) * sp * dt * (1 if CFG["invert_mouse_y"] else -1)
            ix, iy = int(ax), int(ay); ax -= ix; ay -= iy
            if ix or iy:
                inject_mouse_move(ix, iy)

    def close(self):
        self.alive = False
        self._sync(set())

# ----------------------------------------------------------------------------- virtual pads (xbox mode)
class Backend:
    def __init__(self, sim: bool, mode: str = "keyboard"):
        global SIM
        self.vg = None
        self.masks = []
        self.mode = mode
        if mode == "keyboard":
            SIM = sim
            load_cfg()
            if sim:
                print("[sim] simulation mode - key/mouse events are printed, not sent")
            return
        if sim:
            print("[sim] simulation mode - no virtual controller is created")
            return
        ensure_vigem()
        try:
            import vgamepad as vg
            self.vg = vg
            self.masks = [int(getattr(vg.XUSB_BUTTON, "XUSB_GAMEPAD_" + n)) for n in BTN_NAMES]
            vg.VX360Gamepad()  # probe: raises if ViGEmBus driver is missing
        except Exception as e:  # noqa
            print("\nERROR: could not create a virtual Xbox 360 controller:", e)
            print("  Make sure vgamepad is installed (pip install vgamepad) and the ViGEmBus driver is present:")
            print("     https://github.com/nefarius/ViGEmBus/releases   (then run again)")
            print("  Or run with --sim to test the phone UI without a driver.\n")
            sys.exit(1)

    def new_pad(self, on_rumble):
        return InputPad() if self.mode == "keyboard" else Pad(self, on_rumble)

class Pad:
    def __init__(self, be: Backend, on_rumble):
        self.be = be
        self.p = be.vg.VX360Gamepad() if be.vg else None
        if self.p is not None:
            try:
                self.p.register_notification(
                    callback_function=lambda client, target, large, small, led, ud: on_rumble(large, small))
            except Exception:
                pass

    def apply(self, b, lt, rt, lx, ly, rx, ry):
        if self.p is None:
            return
        m = 0
        for i, mask in enumerate(self.be.masks):
            if (b >> i) & 1:
                m |= mask
        r = self.p.report
        r.wButtons = m
        r.bLeftTrigger, r.bRightTrigger = lt, rt
        r.sThumbLX, r.sThumbLY, r.sThumbRX, r.sThumbRY = lx, ly, rx, ry
        self.p.update()

    def close(self):
        if self.p is not None:
            try:
                self.p.unregister_notification()
            except Exception:
                pass
            self.p = None  # dropping the object unplugs the pad

# ----------------------------------------------------------------------------- server
class State:
    pin = "0000"
    port = 8080
    max_pads = 1
    backend: Backend = None  # type: ignore
    lock = threading.Lock()
    clients = []   # active Handler objects
    pads = []      # their pads (released on exit)
    log_lines = []

def log(msg):
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    print(line, flush=True)
    State.log_lines.append(line)
    del State.log_lines[:-50]

class Handler(BaseHTTPRequestHandler):
    server_version = "GamePadRemote/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silence default access log
        pass

    # ---- plain HTTP
    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def is_local(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/ws" and self.headers.get("Upgrade", "").lower() == "websocket":
            return self.websocket()
        if path in ("/", "/index.html"):
            return self._send(200, "text/html; charset=utf-8", (WEB / "index.html").read_bytes())
        if path == "/status":
            ips = local_ips()
            d = {"urls": [f"http://{ip}:{State.port}" for ip in ips],
                 "pads": len(State.clients), "max": State.max_pads, "sim": SIM or (State.backend.mode == "xbox" and State.backend.vg is None),
                 "mode": State.backend.mode}
            if self.is_local():          # PIN is only revealed to the PC itself
                d["pin"] = State.pin
                d["keymap"] = str(keymap_path())
            return self._send(200, "application/json", json.dumps(d).encode())
        self._send(404, "text/plain", b"not found")

    # ---- websocket
    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.rfile.read(n - len(buf))
            if not chunk:
                raise ConnectionError
            buf += chunk
        return buf

    def _recv_frame(self):
        b1, b2 = self._read(2)
        op, n = b1 & 0x0F, b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._read(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._read(8))[0]
        if n > 4096:
            raise ConnectionError
        mask = self._read(4) if b2 & 0x80 else None
        data = self._read(n) if n else b""
        if mask:
            data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
        return op, data

    def _send_frame(self, op, data=b""):
        n = len(data)
        hdr = bytes([0x80 | op]) + (bytes([n]) if n < 126 else b"\x7e" + struct.pack(">H", n))
        with self.slock:
            self.wfile.write(hdr + data)
            self.wfile.flush()

    def send_text(self, s):
        try:
            self._send_frame(1, s.encode())
        except Exception:
            pass

    def websocket(self):
        key = self.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.wfile.flush()
        self.close_connection = True
        self.slock = threading.Lock()
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.connection.settimeout(10)   # phone sends keep-alives; silence = dead link
        pad = None
        ip = self.client_address[0]
        try:
            op, data = self._recv_frame()
            if op != 1 or not data.startswith(b"H"):
                return
            if data[1:].decode(errors="ignore") != State.pin:
                log(f"Wrong PIN from {ip}")
                self.send_text("BAD"); time.sleep(1); return
            with State.lock:
                if len(State.clients) >= State.max_pads:
                    self.send_text("FULL"); return
                pad = State.backend.new_pad(lambda l, s: self.send_text(f"V {l} {s}"))
                State.clients.append(self)
                State.pads.append(pad)
                num = len(State.clients)
            log(f"Controller {num} connected: {ip}")
            self.send_text(f"OK {num}")
            while True:
                op, data = self._recv_frame()
                if op == 8:
                    break
                if op == 9:
                    self._send_frame(10, data)
                elif op == 1 and data[:1] == b"S":
                    v = data.split()
                    if len(v) == 8:
                        b, lt, rt, lx, ly, rx, ry = (int(x) for x in v[1:])
                        pad.apply(b & 0x7FFF, clamp(lt, 0, 255), clamp(rt, 0, 255),
                                  clamp(lx, -32768, 32767), clamp(ly, -32768, 32767),
                                  clamp(rx, -32768, 32767), clamp(ry, -32768, 32767))
        except (ConnectionError, OSError, ValueError, struct.error):
            pass
        finally:
            if pad is not None:
                pad.close()
                if pad in State.pads:
                    State.pads.remove(pad)
                with State.lock:
                    if self in State.clients:
                        State.clients.remove(self)
                log(f"Controller disconnected: {ip}")

class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def fatal(msg):
    print("ERROR:", msg, flush=True)
    if os.name == "nt" and (getattr(sys, "frozen", False) or not sys.stdin or not sys.stdin.isatty()):
        try:
            _msgbox(msg)
        except Exception:
            pass
    sys.exit(1)

def other_instance(port):
    """True if one of OUR hosts already answers on this port."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=1) as r:
            return "mode" in json.loads(r.read().decode())
    except Exception:
        return False

def discovery_loop(port):
    """Answer the phone app's UDP broadcast so it can list this PC automatically."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", DISCOVERY_PORT))
    except OSError:
        return
    name = socket.gethostname().replace("|", " ")
    while True:
        try:
            data, addr = s.recvfrom(256)
            if data.startswith(b"RGDISCOVER"):
                s.sendto(f"RGHOST|{port}|{name}|{State.backend.mode}".encode(), addr)
        except OSError:
            pass

def shutdown_all():
    """Release every key/mouse button that a phone is still holding."""
    for pad in list(State.pads):
        try:
            pad.close()
        except Exception:
            pass
    State.pads.clear()

def run_gui(port):
    """Small control window (PIN, addresses, status). Closing it quits the host."""
    import tkinter as tk
    root = tk.Tk()
    root.title("Game Pad Remote")
    root.geometry("460x380")
    root.resizable(False, False)
    root.configure(bg="#0f1115")
    fg, dim = "#e8eaf0", "#9aa3b5"
    tk.Label(root, text="Game Pad Remote", font=("Segoe UI", 18, "bold"), bg="#0f1115", fg=fg).pack(pady=(14, 0))
    tk.Label(root, text="PIN", font=("Segoe UI", 10), bg="#0f1115", fg=dim).pack()
    tk.Label(root, text=State.pin, font=("Segoe UI", 34, "bold"), bg="#0f1115", fg="#fde68a").pack()
    urls = tk.Label(root, text="", font=("Consolas", 11), bg="#0f1115", fg="#7dd3fc", justify="center")
    urls.pack(pady=6)
    tk.Label(root, text="Open the Game Pad Remote app on your phone (it finds this PC),\n"
                        "or open one of the addresses above in the phone browser.",
             font=("Segoe UI", 9), bg="#0f1115", fg=dim, justify="center").pack()
    status = tk.Label(root, text="", font=("Segoe UI", 11, "bold"), bg="#0f1115", fg="#4ade80")
    status.pack(pady=8)
    row = tk.Frame(root, bg="#0f1115"); row.pack(pady=4)
    def open_console():
        webbrowser.open(f"http://localhost:{port}/")
    def edit_keys():
        try:
            load_cfg(); os.startfile(str(keymap_path()))  # type: ignore[attr-defined]
        except Exception:
            pass
    tk.Button(row, text="Open gamepad console", command=open_console, width=22).grid(row=0, column=0, padx=4, pady=3)
    tk.Button(row, text="Edit key mapping", command=edit_keys, width=22).grid(row=0, column=1, padx=4, pady=3)
    tk.Button(root, text="Quit", command=root.destroy, width=16).pack(pady=8)
    def refresh():
        ips = local_ips()
        urls.config(text="\n".join(f"http://{ip}:{port}" for ip in ips) or "No network found - connect Wi-Fi/Ethernet")
        n = len(State.clients)
        status.config(text="Phone connected" if n else "Waiting for phone...", fg="#4ade80" if n else dim)
        root.after(1500, refresh)
    refresh()
    root.mainloop()

def main():
    if sys.stdout is None:                      # windowed exe has no console
        sys.stdout = open(cfg_dir() / "host.log", "a", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = sys.stdout
    ap = argparse.ArgumentParser(description="Game Pad Remote PC host")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--no-browser", action="store_true", help="do not open the host console in the browser")
    ap.add_argument("--gui", action="store_true", help="show the small control window (default in the .exe)")
    ap.add_argument("--no-gui", action="store_true")
    ap.add_argument("--sim", action="store_true", help="simulate (print events instead of sending them)")
    ap.add_argument("--mode", choices=["keyboard", "xbox"], default="keyboard",
                    help="keyboard = free mode, no driver (default); xbox = virtual Xbox 360 pad (ViGEmBus)")
    a = ap.parse_args()
    gui = (a.gui or (getattr(sys, "frozen", False) and os.name == "nt")) and not a.no_gui

    # already running? just open its console
    for p in range(a.port, a.port + 11):
        if other_instance(p):
            print(f"Already running on port {p}.")
            if not a.no_browser:
                webbrowser.open(f"http://localhost:{p}/")
            return

    State.pin = load_pin()
    State.backend = Backend(a.sim, a.mode)
    State.max_pads = 1 if a.mode == "keyboard" else MAX_PADS
    srv = None
    for p in range(a.port, a.port + 11):         # next free port if 8080 is taken
        try:
            srv = Server(("0.0.0.0", p), Handler); State.port = p; break
        except OSError:
            continue
    if srv is None:
        fatal(f"Cannot listen on ports {a.port}-{a.port + 10}. Close the program using them.")

    print("=" * 56)
    print(f" Game Pad Remote {VERSION} - host running")
    print(f" Mode: {'keyboard + mouse (no driver)' if a.mode == 'keyboard' else 'virtual Xbox 360 pad'}")
    if a.mode == "keyboard":
        print(f" Key mapping file: {keymap_path()}")
    print(f" PIN : {State.pin}")
    for ip in local_ips():
        print(f" Phone browser -> http://{ip}:{State.port}")
    print(f" This PC       -> http://localhost:{State.port}")
    print(" Ctrl+C to stop")
    print("=" * 56, flush=True)

    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=discovery_loop, args=(State.port,), daemon=True).start()
    if not a.no_browser and not gui:
        threading.Timer(0.7, lambda: webbrowser.open(f"http://localhost:{State.port}/")).start()
    try:
        if gui:
            try:
                run_gui(State.port)
            except Exception as e:               # no Tk? keep serving and use the browser console
                print("Control window unavailable:", e, flush=True)
                webbrowser.open(f"http://localhost:{State.port}/")
                while True:
                    time.sleep(3600)
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_all()
        srv.shutdown()
        srv.server_close()

if __name__ == "__main__":
    main()
