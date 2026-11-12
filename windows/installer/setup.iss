; Built by Inno Setup in CI. Expects ..\publish\RemoteGamepad.exe (PyInstaller output) and ..\RemoteGamepad.ico
; Free mode needs NO driver - the installer only copies the program, adds shortcuts and opens the firewall.
[Setup]
AppName=Game Pad Remote
AppVersion=1.1.0
AppPublisher=Remote Gamepad
DefaultDirName={autopf}\RemoteGamepad
DefaultGroupName=Game Pad Remote
OutputDir=..\dist
OutputBaseFilename=RemoteGamepadSetup
SetupIconFile=..\RemoteGamepad.ico
UninstallDisplayIcon={app}\RemoteGamepad.exe
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Game Pad Remote
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Files]
Source: "..\publish\RemoteGamepad.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Game Pad Remote"; Filename: "{app}\RemoteGamepad.exe"
Name: "{autodesktop}\Game Pad Remote"; Filename: "{app}\RemoteGamepad.exe"; Tasks: desktopicon

[Run]
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""Game Pad Remote (web)"" dir=in action=allow protocol=TCP localport=8080-8090 profile=private,public"; Flags: runhidden
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""Game Pad Remote (discovery)"" dir=in action=allow protocol=UDP localport=26761 profile=private,public"; Flags: runhidden
Filename: "{app}\RemoteGamepad.exe"; Description: "Launch Game Pad Remote"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""Game Pad Remote (web)"""; Flags: runhidden
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""Game Pad Remote (discovery)"""; Flags: runhidden
