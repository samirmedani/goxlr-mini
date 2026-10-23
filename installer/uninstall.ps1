<#
Desinstalle GoXLR Mini : tache du moteur, appli, raccourcis, demarrage avec la session, dossier d'installation.
Les reglages (C:\ProgramData\GoXLR Mini) sont gardes, sauf avec -RemoveData.
Usage : Desinstaller.cmd, ou "Programmes et fonctionnalites".
#>
param([switch]$RemoveData, [string]$ForUser, [switch]$Quiet)
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$name = 'GoXLR Mini'
$dst = Join-Path $env:ProgramFiles $name
$data = Join-Path $env:ProgramData $name

$me = [Security.Principal.WindowsIdentity]::GetCurrent()
$admin = (New-Object Security.Principal.WindowsPrincipal $me).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
# le script ne peut pas effacer son propre dossier : il se relance depuis le dossier temporaire
$self = $PSCommandPath
if ($self.StartsWith($dst + '\', [StringComparison]::OrdinalIgnoreCase) -or -not $admin) {
  $tmp = Join-Path $env:TEMP 'goxlr-mini-uninstall.ps1'
  if ($self -ne $tmp) { Copy-Item $self $tmp -Force }
  $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $tmp + '"'))
  if ($RemoveData) { $a += '-RemoveData' }
  if ($ForUser) { $a += @('-ForUser', ('"' + $ForUser + '"')) }
  if ($Quiet) { $a += '-Quiet' }
  if ($admin) { Start-Process powershell.exe -ArgumentList $a -Wait -NoNewWindow } else { Start-Process powershell.exe -Verb RunAs -ArgumentList $a -Wait }
  exit
}

Write-Host 'GoXLR Mini : desinstallation' -ForegroundColor Cyan
foreach ($t in $name, 'GoXLR Mini Update', 'GoXLR Mini (premier lancement)') {
  Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
}
Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object { $_.ExecutablePath -and ($_.ExecutablePath.StartsWith($dst + '\', [StringComparison]::OrdinalIgnoreCase) -or $_.ExecutablePath.StartsWith($data + '\', [StringComparison]::OrdinalIgnoreCase)) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 1

function Get-UserDesktop($sid, $prof) {
  # Bureau reel du compte (redirige vers OneDrive, par exemple), lu dans sa ruche ; sinon <profil>\Desktop
  $k = "Registry::HKEY_USERS\$sid\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
  $raw = $null
  if (Test-Path $k) { $raw = (Get-Item $k).GetValue('Desktop', $null, 'DoNotExpandEnvironmentNames') }
  if ($raw -and $prof) { return [Environment]::ExpandEnvironmentVariables([regex]::Replace($raw, '%USERPROFILE%', $prof.Replace('$', '$$'), 'IgnoreCase')) }
  if ($prof) { return (Join-Path $prof 'Desktop') }
  return $null
}
$users = @($me.Name)
if ($ForUser) { $users += $ForUser }
$recorded = (Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\GoXLRMini' -ErrorAction SilentlyContinue).InstalledFor
if ($recorded) { $users += $recorded }
foreach ($u in $users | Select-Object -Unique) {
  try {
    $sid = (New-Object Security.Principal.NTAccount($u)).Translate([Security.Principal.SecurityIdentifier]).Value
    Remove-ItemProperty "Registry::HKEY_USERS\$sid\Software\Microsoft\Windows\CurrentVersion\Run" -Name $name -ErrorAction SilentlyContinue
    $profile = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\$sid" -ErrorAction SilentlyContinue).ProfileImagePath
    if ($profile) {
      foreach ($d in @((Get-UserDesktop $sid $profile), (Join-Path $profile 'Desktop')) | Where-Object { $_ } | Select-Object -Unique) { Remove-Item (Join-Path $d ($name + '.lnk')) -Force -ErrorAction SilentlyContinue }
      if ($RemoveData) { Remove-Item (Join-Path $profile ('AppData\Local\' + $name)) -Recurse -Force -ErrorAction SilentlyContinue }
    }
  } catch { }
}
Remove-Item (Join-Path ([Environment]::GetFolderPath('CommonPrograms')) ($name + '.lnk')) -Force -ErrorAction SilentlyContinue
Remove-Item 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\GoXLRMini' -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $dst -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $dst) { Write-Warning "Certains fichiers de $dst sont encore utilises : ils partiront au prochain redemarrage." }
if ($RemoveData) { Remove-Item $data -Recurse -Force -ErrorAction SilentlyContinue; Write-Host '  Reglages supprimes.' }
else { Write-Host ("  Reglages gardes dans " + $data + '.') }
Write-Host 'GoXLR Mini est desinstalle.' -ForegroundColor Green
if (-not $Quiet) { Read-Host 'Appuie sur Entree pour fermer' | Out-Null }
