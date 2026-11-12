# Game Pad Remote
Use your phone as a game controller for a Windows PC - **no driver needed** (free mode: the phone becomes keyboard keys + mouse look).

* **PC program** (`RemoteGamepad.exe` / installer) - small window with PIN + addresses; also serves the gamepad page.
* **Phone** - either the **Android app** (finds the PC automatically, adds tilt/gyro + vibration) or just any phone browser on `http://<PC-IP>:8080`.
* The PC console (`http://localhost:8080`) shows the **same gamepad GUI** as the phone.

## Get the APK and the installer EXE (nothing to install locally)
1. Create a free GitHub repo and push this folder to it.
2. Open **Actions → Build APK and Windows installer** (runs on every push; ~6 min).
3. Download the artifacts:
   * `GamePadRemote-APK` → `GamePadRemote.apk` (install on phone, allow "unknown sources")
   * `GamePadRemote-Windows-Installer` → `RemoteGamepadSetup.exe`  (or `...Portable-EXE` → `RemoteGamepad.exe`)
4. To publish a release page: `git tag v1.1.0 && git push --tags` - the APK and EXEs are attached automatically.
Windows may show SmartScreen ("unknown publisher") because the EXE is unsigned: *More info → Run anyway*.

## Use
1. Install/run **Game Pad Remote** on the PC. Note the **PIN** in its window.
2. Phone: open the app → tap your PC in the list (or type the address) → enter the PIN once.
3. Click into your game on the PC and play.

Default keys: left stick = WASD · right stick = mouse look · A Space · B Ctrl · X R · Y F · LB Q · RB E · LT right-click · RT left-click · L3 Shift · R3 C · Start Esc · Back Tab · D-pad arrows.
Change them (and mouse speed/dead zone) in `%APPDATA%\RemoteGamepad\keymap.json` (window button: *Edit key mapping*; restart the program after editing).
Games running **as administrator** only accept input from an administrator-run Game Pad Remote.

## Connection types (all are plain IP - same page, same PIN)
| Link | How |
|---|---|
| Wi-Fi | phone and PC on the same router |
| Ethernet | PC on cable, phone on Wi-Fi of the same router |
| USB | phone *USB tethering* ON, then Search again / type the PC IP of the new adapter |
| Bluetooth | pair, phone *Bluetooth tethering* ON, then type the PC IP of the Bluetooth adapter |
(A browser/WebView cannot open a raw Bluetooth gamepad link, so Bluetooth works via tethering.)

## Develop / test
* Run from source: `python windows/host.py` (Python 3.9+, no packages). `--sim` prints key events instead of sending them; `--no-gui`, `--port N`.
* Tests: `python windows/tests/test_host.py` (CI runs them on Linux + Windows).
* Build EXE locally: `pip install pyinstaller` then in `windows/`: `pyinstaller --onefile --noconsole --name RemoteGamepad --icon RemoteGamepad.ico --add-data "web;web" --distpath publish host.py`
* Build APK locally: open `android/` in Android Studio, or `gradle -p android assembleRelease`.
* Optional real Xbox-360 pad (needs the ViGEmBus driver + `pip install vgamepad`): `python windows/host.py --mode xbox`.

## Protocol (WebSocket, path `/ws`)
`H<pin>` → `OK <n>`/`BAD`/`FULL`; then `S <buttons> <lt> <rt> <lx> <ly> <rx> <ry>`. Discovery: UDP `RGDISCOVER` to port 26761 → `RGHOST|port|name|mode`.
