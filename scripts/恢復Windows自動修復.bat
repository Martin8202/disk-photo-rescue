@echo off
rem Run as administrator AFTER the rescue is finished and the failing drive is UNPLUGGED.
rem Reverts what the drive-prep batch and the VM setup changed. Full checklist: docs, "restore the computer" page.
net session >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Please right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer" /v NoDriveTypeAutoRun /f >nul 2>&1
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer" /v NoDriveTypeAutoRun /f >nul 2>&1
fsutil behavior set disablelastaccess 2
sc config svsvc start= demand
schtasks /Change /TN "\Microsoft\Windows\Chkdsk\ProactiveScan" /Enable
rem Only touches the Seagate disk if it is still connected. Unplugged, it simply stays read-only (fine for a retired disk).
powershell -NoProfile -Command "Get-Disk | Where-Object FriendlyName -like '*Seagate Expansion*' | Set-Disk -IsOffline $false; Get-Disk | Where-Object FriendlyName -like '*Seagate Expansion*' | Set-Disk -IsReadOnly $false"
rem Scheduled tasks created during the rescue: every task named PhotoRescue*, plus the photo-move tasks whose names
rem start with the Chinese word for "photo move" (built from char codes so this file stays pure ASCII).
powershell -NoProfile -Command "$z = -join [char[]](0x7167,0x7247,0x642C,0x79FB); Get-ScheduledTask | Where-Object { $_.TaskName -like 'PhotoRescue*' -or $_.TaskName -like ($z + '*') } | Unregister-ScheduledTask -Confirm:$false"
rem ddrescue VM environment (setup-host.ps1): SMB share, firewall rule, local account and its hidden-from-login entry.
rem Folders C:\PhotoRescueDD and C:\PhotoRescueVM are kept: delete them yourself after checking the cloud upload.
powershell -NoProfile -Command "Remove-SmbShare -Name PhotoRescueDD -Force -ErrorAction SilentlyContinue; Get-NetFirewallRule -DisplayName 'PhotoRescue VM SMB' -ErrorAction SilentlyContinue | Remove-NetFirewallRule; Remove-LocalUser -Name photorescue -ErrorAction SilentlyContinue"
reg delete "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList" /v photorescue /f >nul 2>&1
echo.
echo Done: AutoPlay restored, last-access updates back to system managed, Spot Verifier Manual, ProactiveScan enabled,
echo rescue scheduled tasks removed, VM share / firewall rule / account removed.
echo Next: run the check in the docs, then decide about C:\PhotoRescueDD, C:\PhotoRescueVM and the work folder.
pause
