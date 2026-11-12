@echo off
:: Run as Administrator once so the phone can reach the PC (TCP 8080).
netsh advfirewall firewall add rule name="Game Pad Remote" dir=in action=allow protocol=TCP localport=8080 profile=private,public
pause
