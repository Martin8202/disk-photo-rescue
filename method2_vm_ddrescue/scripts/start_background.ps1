# Starts one of the chain scripts in this folder detached from the current terminal / AI session,
# so it keeps running after that session ends. Kept ASCII-only on purpose: Windows PowerShell 5.1
# reads BOM-less .ps1 files in the system code page, which garbles Chinese text.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File start_background.ps1 <script.sh> [args...]
param(
    [Parameter(Mandatory = $true)][string]$Script,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$ScriptArgs
)
$ErrorActionPreference = "Stop"
$sh = "C:\Program Files\Git\bin\bash.exe"
if (-not (Test-Path $sh)) { $sh = "C:\Program Files\Git\usr\bin\bash.exe" }
if (-not (Test-Path $sh)) { throw "Git Bash not found" }

$path = Join-Path $PSScriptRoot $Script
if (-not (Test-Path $path)) { throw "Script not found: $path" }
$name = Split-Path $path -Leaf

# Do not start a second copy of the same chain script.
# Skip shells whose command line mentions start_background: that is the caller itself (e.g. an AI tool
# running "bash -c '... start_background.ps1 <script>'"), not a running copy of the script.
$running = Get-CimInstance Win32_Process -Filter "Name='bash.exe'" |
    Where-Object { $_.CommandLine -like "*$name*" -and $_.CommandLine -notlike "*start_background*" }
if ($running) {
    Write-Host "Already running (PID $($running.ProcessId -join ',')), not starting another one"
    exit 0
}

$argList = @('"' + ($path -replace '\\', '/') + '"') + @($ScriptArgs | ForEach-Object { '"' + $_ + '"' })
$p = Start-Process -FilePath $sh -ArgumentList $argList -WindowStyle Hidden -PassThru
Write-Host "Started, PID = $($p.Id)"
