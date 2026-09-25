@echo off
rem Right-click and "Run as administrator". Run ONCE, after VMware Workstation Pro is installed.
rem Creates the SMB share C:\PhotoRescueDD for the ddrescue VM (spec step E5).
net session >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Please right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\PhotoRescueVM\setup-host.ps1"
echo.
echo Expected last line: Done. Connection details saved to C:\PhotoRescueVM\share-password.txt
pause