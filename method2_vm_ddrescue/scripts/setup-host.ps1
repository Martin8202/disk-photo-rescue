# Sets up the host side for the ddrescue VM (runbook: docs, method 2, step E5). Run ONCE as administrator, AFTER VMware is installed.
#  - folder C:\PhotoRescueDD shared as \\host\PhotoRescueDD, only for local account "photorescue" (random password, hidden from login screen)
#  - firewall: allow SMB (TCP 445) inbound ONLY from the VMware NAT subnet (VMnet8)
# Safe to run again: it resets the password and recreates the rule.
$ErrorActionPreference = "Stop"
$dir = "C:\PhotoRescueDD"; $vmdir = "C:\PhotoRescueVM"; $user = "photorescue"; $share = "PhotoRescueDD"; $rule = "PhotoRescue VM SMB"

$nic = Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "VMware Network Adapter VMnet8" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $nic) { throw "VMware NAT adapter (VMnet8) not found. Install VMware Workstation Pro first." }
$ip = [System.Net.IPAddress]::Parse($nic.IPAddress).GetAddressBytes(); [array]::Reverse($ip)
$mask = [uint32](([uint64]4294967295 -shl (32 - $nic.PrefixLength)) -band [uint64]4294967295)   # not 0xFFFFFFFF: PowerShell 5.1 reads that as -1
$net = [BitConverter]::ToUInt32($ip, 0) -band $mask
$nb = [BitConverter]::GetBytes([uint32]$net); [array]::Reverse($nb)
$subnet = "{0}/{1}" -f ([System.Net.IPAddress]::new($nb)).IPAddressToString, $nic.PrefixLength
Write-Host "  VMware NAT subnet: $subnet (host address $($nic.IPAddress))"

$chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
$bytes = New-Object byte[] 20; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$pw = "Pr9-" + (-join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] }))
$sec = ConvertTo-SecureString $pw -AsPlainText -Force
if (Get-LocalUser -Name $user -ErrorAction SilentlyContinue) {
    Set-LocalUser -Name $user -Password $sec -PasswordNeverExpires $true
} else {
    New-LocalUser -Name $user -Password $sec -PasswordNeverExpires -AccountNeverExpires -Description "SMB access for the photo-rescue VM only" | Out-Null
}
$ul = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList"
New-Item -Path $ul -Force | Out-Null
New-ItemProperty -Path $ul -Name $user -Value 0 -PropertyType DWord -Force | Out-Null
Write-Host "  local account '$user' ready (hidden from login screen)"

New-Item -ItemType Directory -Force -Path $dir, $vmdir | Out-Null
icacls $dir /grant "${user}:(OI)(CI)M" | Out-Null
if (Get-SmbShare -Name $share -ErrorAction SilentlyContinue) {
    Grant-SmbShareAccess -Name $share -AccountName $user -AccessRight Change -Force | Out-Null
} else {
    New-SmbShare -Name $share -Path $dir -ChangeAccess $user | Out-Null
}
Write-Host "  share \\$env:COMPUTERNAME\$share -> $dir"

Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP -LocalPort 445 -RemoteAddress $subnet -Action Allow -Profile Any | Out-Null
Write-Host "  firewall: TCP 445 allowed only from $subnet"

Set-Content -Path (Join-Path $vmdir "share-password.txt") -Encoding ASCII -Value @(
    "host=$($nic.IPAddress)", "share=$share", "user=$user", "password=$pw", "subnet=$subnet")
Write-Host ""
Write-Host "Done. Connection details saved to $vmdir\share-password.txt"
