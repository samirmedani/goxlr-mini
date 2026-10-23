<#
Installe ou met a jour GoXLR Mini.
  - copie les fichiers dans "Program Files\GoXLR Mini" ;
  - tache planifiee "GoXLR Mini" : le moteur demarre avec Windows (compte systeme), quel que soit l'utilisateur ;
  - raccourcis (menu Demarrer, Bureau), demarrage de l'appli avec la session, entree dans "Programmes et fonctionnalites".
Les reglages (C:\ProgramData\GoXLR Mini\state.json) sont gardes d'une version a l'autre.

Usage : double-clic sur Installer.cmd (les droits administrateur sont demandes).
Options : -NoStartup  (pas de demarrage avec la session)   -NoDesktop  (pas de raccourci sur le Bureau)
          -ForUser <compte>  (raccourcis et demarrage pour ce compte, s'il a une session ouverte)
          -ImportState <state.json>  (reprend des reglages existants si aucun n'est encore installe)   -Quiet
          -NoLaunch  (n'ouvre pas l'appli a la fin)   -StatusFile <fichier>  (etapes pour GoXLR-Mini-Setup.exe)
Code de sortie : 0 si l'installation est faite, 1 sinon.
#>
param([switch]$NoStartup, [switch]$NoDesktop, [string]$ForUser, [string]$ImportState, [switch]$Quiet,
      [switch]$NoLaunch, [string]$StatusFile)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$src = $PSScriptRoot

$me = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal $me).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $PSCommandPath + '"'))
  if ($NoStartup) { $a += '-NoStartup' }
  if ($NoDesktop) { $a += '-NoDesktop' }
  if ($ForUser) { $a += @('-ForUser', ('"' + $ForUser + '"')) }
  if ($ImportState) { $a += @('-ImportState', ('"' + $ImportState + '"')) }
  if ($Quiet) { $a += '-Quiet' }
  if ($NoLaunch) { $a += '-NoLaunch' }
  if ($StatusFile) { $a += @('-StatusFile', ('"' + $StatusFile + '"')) }
  $p = Start-Process powershell.exe -Verb RunAs -ArgumentList $a -Wait -PassThru
  exit $p.ExitCode
}

function Say($m) { Write-Host ('  ' + $m) }
function Status($s) { if ($StatusFile) { Add-Content -LiteralPath $StatusFile -Value $s -Encoding UTF8 } }
trap {
  Status ('error|' + $_.Exception.Message)
  Write-Host ('  Erreur : ' + $_.Exception.Message) -ForegroundColor Red
  if (-not $Quiet) { Read-Host 'Appuie sur Entree pour fermer' | Out-Null }
  exit 1
}
function Get-UserDesktop($sid, $prof) {
  # Bureau reel du compte (redirige vers OneDrive, par exemple), lu dans sa ruche ; sinon <profil>\Desktop
  $k = "Registry::HKEY_USERS\$sid\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
  $raw = $null
  if (Test-Path $k) { $raw = (Get-Item $k).GetValue('Desktop', $null, 'DoNotExpandEnvironmentNames') }
  if ($raw -and $prof) { return [Environment]::ExpandEnvironmentVariables([regex]::Replace($raw, '%USERPROFILE%', $prof.Replace('$', '$$'), 'IgnoreCase')) }
  if ($prof) { return (Join-Path $prof 'Desktop') }
  return $null
}
$name = 'GoXLR Mini'
$dst = Join-Path $env:ProgramFiles $name
$data = Join-Path $env:ProgramData $name
$man = Get-Content (Join-Path $src 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host ''
Write-Host ("GoXLR Mini " + $man.version + " : installation") -ForegroundColor Cyan

$dll = Join-Path $env:ProgramFiles 'TC-Helicon\GoXLR_Audio_Driver\x64\goxlr_audioapi_x64.dll'
if (-not (Test-Path $dll)) { Write-Warning "Pilote officiel GoXLR introuvable. Installe-le (voir le README) : GoXLR Mini l'attendra." }
if (Get-Process -Name 'goxlr-daemon', 'goxlr-utility' -ErrorAction SilentlyContinue) {
  Write-Warning "GoXLR Utility est ouvert : ferme-le. Deux logiciels ne peuvent pas piloter la GoXLR en meme temps."
}

# compte cible des raccourcis et du demarrage (par defaut : celui qui installe)
$user = if ($ForUser) { $ForUser } else { $me.Name }
$sid = (New-Object Security.Principal.NTAccount($user)).Translate([Security.Principal.SecurityIdentifier]).Value
$profile = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\$sid" -ErrorAction SilentlyContinue).ProfileImagePath
if (-not (Test-Path "Registry::HKEY_USERS\$sid")) { Write-Warning "Le compte $user n'a pas de session ouverte : demarrage avec la session non configure." }

Status 'stop'
Say 'Arret de la version en place...'
Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($dst + '\', [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 1

Status 'copy'
Say ("Copie dans " + $dst + '...')
New-Item -ItemType Directory -Force $dst, $data | Out-Null
foreach ($rel in $man.files.PSObject.Properties.Name) {
  $to = Join-Path $dst $rel
  New-Item -ItemType Directory -Force (Split-Path $to) | Out-Null
  Copy-Item (Join-Path $src $rel) $to -Force
}
Get-ChildItem $dst -Recurse -File | Unblock-File
if ($ImportState -and (Test-Path $ImportState) -and -not (Test-Path (Join-Path $data 'state.json'))) {
  Copy-Item $ImportState (Join-Path $data 'state.json')
  Say 'Reglages existants repris.'
}

Status 'task'
Say 'Tache du moteur (demarre avec Windows)...'
$action = New-ScheduledTaskAction -Execute (Join-Path $dst 'python\pythonw.exe') -Argument ('"' + (Join-Path $dst 'goxlrctl.py') + '" daemon') -WorkingDirectory $dst
$triggers = @((New-ScheduledTaskTrigger -AtStartup), (New-ScheduledTaskTrigger -AtLogOn))
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description 'GoXLR Mini : moteur qui pilote la GoXLR Mini (interface sur http://127.0.0.1:14565)' -Force | Out-Null
Start-ScheduledTask -TaskName $name

Status 'links'
$exe = Join-Path $dst ('app\' + $name + '.exe')
$ico = Join-Path $dst 'app\app.ico'
$ws = New-Object -ComObject WScript.Shell
$links = @(Join-Path ([Environment]::GetFolderPath('CommonPrograms')) ($name + '.lnk'))
$desk = Get-UserDesktop $sid $profile
if (-not $NoDesktop -and $desk) { $links += Join-Path $desk ($name + '.lnk') }
foreach ($l in $links) {
  if (-not (Test-Path (Split-Path $l))) { continue }
  $s = $ws.CreateShortcut($l); $s.TargetPath = $exe; $s.WorkingDirectory = (Split-Path $exe)
  $s.IconLocation = "$ico,0"; $s.Description = 'Piloter la GoXLR Mini'; $s.Save()
}
$run = "Registry::HKEY_USERS\$sid\Software\Microsoft\Windows\CurrentVersion\Run"
if (Test-Path "Registry::HKEY_USERS\$sid") {
  if (-not (Test-Path $run)) { New-Item $run -Force | Out-Null }
  if ($NoStartup) { Remove-ItemProperty $run -Name $name -ErrorAction SilentlyContinue }
  else { Set-ItemProperty $run -Name $name -Value ('"' + $exe + '" --tray') }
}

$key = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\GoXLRMini'
New-Item $key -Force | Out-Null
$vals = [ordered]@{ DisplayName = $name; DisplayVersion = [string]$man.version; Publisher = 'GoXLR Mini (logiciel libre)'
  DisplayIcon = $ico; InstallLocation = $dst; URLInfoAbout = 'https://github.com/samirmedani/goxlr-mini'
  InstalledFor = $user
  UninstallString = ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $dst 'uninstall.ps1') + '"') }
foreach ($k in $vals.Keys) { New-ItemProperty $key -Name $k -Value $vals[$k] -PropertyType String -Force | Out-Null }
foreach ($k in 'NoModify', 'NoRepair') { New-ItemProperty $key -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }

Status 'start'
Say 'Demarrage du moteur...'
$ok = $false
$seen = -1
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep 1
  try {
    $h = Invoke-RestMethod http://127.0.0.1:14565/api/health -TimeoutSec 3
    if ($h.version -eq $man.version) {
      $ok = $true
      if ($seen -lt 0) { $seen = $i }
      if ($h.connected -or $i - $seen -ge 6) { break }      # la GoXLR se reconnecte en une ou deux secondes
    }
  } catch { }
}
if ($ok) { Say ("Moteur " + $h.version + " en route : GoXLR " + $(if ($h.connected) { 'connectee' } else { 'pas encore detectee' }) + '.') }
else { Write-Warning 'Le moteur ne repond pas encore. Journal : C:\ProgramData\GoXLR Mini\goxlrctl.log' }

# l'appli se lance sans droits administrateur, dans la session du compte cible
if (-not $NoLaunch -and (Test-Path "Registry::HKEY_USERS\$sid")) {
  try {
    $t = 'GoXLR Mini (premier lancement)'
    $p = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $arg = if ($Quiet) { '--tray' } else { '' }
    if ($arg) { $act = New-ScheduledTaskAction -Execute $exe -Argument $arg } else { $act = New-ScheduledTaskAction -Execute $exe }
    Register-ScheduledTask -TaskName $t -Action $act -Principal $p -Force | Out-Null
    Start-ScheduledTask -TaskName $t
    Start-Sleep 3
    Unregister-ScheduledTask -TaskName $t -Confirm:$false
  } catch { Write-Warning ("Lance GoXLR Mini depuis le menu Demarrer (" + $_.Exception.Message + ')') }
}
Write-Host ''
Status ('ok|' + $(if ($ok -and $h.connected) { 'connected' } elseif ($ok) { 'absent' } else { 'starting' }))
Write-Host ("GoXLR Mini " + $man.version + " est installe.") -ForegroundColor Green
if (-not $Quiet) { Read-Host 'Appuie sur Entree pour fermer' | Out-Null }
exit 0
