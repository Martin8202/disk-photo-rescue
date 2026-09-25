@echo off
rem Right-click and "Run as administrator". Run it BEFORE plugging the Seagate drive in.
rem Makes Windows leave the failing drive alone: no AutoPlay window, no last-access writes,
rem no self-repair, and the disk itself set READ-ONLY (Windows remembers this for the disk).
net session >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Please right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
echo [1/5] Disable AutoPlay (no Explorer window when a drive is plugged in)...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer" /v NoDriveTypeAutoRun /t REG_DWORD /d 255 /f >nul
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer" /v NoDriveTypeAutoRun /t REG_DWORD /d 255 /f >nul
echo [2/5] Disable NTFS last-access-time updates (reading a file no longer writes to the MFT)...
fsutil behavior set disablelastaccess 1
echo [3/5] Stop Spot Verifier and Chkdsk ProactiveScan...
sc stop svsvc >nul 2>&1
sc config svsvc start= disabled >nul
schtasks /Change /TN "\Microsoft\Windows\Chkdsk\ProactiveScan" /Disable >nul
echo [4/5] Waiting for the Seagate drive ... (plug it in now: power first, then USB)
:waitdisk
powershell -NoProfile -Command "if (Get-Disk -ErrorAction SilentlyContinue | Where-Object FriendlyName -like '*Seagate Expansion*') { exit 0 } else { exit 1 }"
if errorlevel 1 (
  timeout /t 5 /nobreak >nul
  goto waitdisk
)
echo       Seagate drive detected. Setting it READ-ONLY...
powershell -NoProfile -Command "Get-Disk | Where-Object FriendlyName -like '*Seagate Expansion*' | Set-Disk -IsReadOnly $true"
echo [5/5] Waiting for E: and disabling NTFS self-healing on it...
:waitE
if not exist E:\ (
  timeout /t 5 /nobreak >nul
  goto waitE
)
fsutil repair set E: 0 >nul 2>&1
echo.
echo ===== Result =====
powershell -NoProfile -Command "Get-Disk | Where-Object FriendlyName -like '*Seagate Expansion*' | Select-Object Number, FriendlyName, IsReadOnly, IsOffline | Format-Table -AutoSize"
fsutil behavior query disablelastaccess
fsutil repair query E:
echo.
echo Expected: IsReadOnly True, DisableLastAccess = 1, self-healing disabled.
pause
