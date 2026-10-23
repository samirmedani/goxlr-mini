<#
Fabrique la release de GoXLR Mini : dist\GoXLR-Mini.zip et dist\GoXLR-Mini.sha256.
A lancer sous Windows avec le SDK .NET 10 (et Git pour graver le commit). Utilise par la release GitHub.
Contenu : Python embarque officiel (empreinte verifiee), appli .NET autonome (aucun runtime a installer),
moteur, interface, installeur, licences, manifest.json (version, commit, empreinte de chaque fichier).
#>
param([string]$Out = (Join-Path $PSScriptRoot '..\dist'))
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
New-Item -ItemType Directory -Force $Out | Out-Null
$Out = (Resolve-Path $Out).Path
$nl = [string][char]13 + [char]10
$utf8 = New-Object Text.UTF8Encoding $false

$version = (Select-String -Path (Join-Path $root 'engine\goxlrctl.py') -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
$appVersion = ([xml](Get-Content (Join-Path $root 'app\GoXLRMini.csproj'))).Project.PropertyGroup.Version | Where-Object { $_ } | Select-Object -First 1
if ($appVersion -ne $version) { throw "Versions differentes : moteur $version, appli $appVersion" }
Write-Host "GoXLR Mini $version"

$stage = Join-Path $Out 'payload'
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $stage | Out-Null

# Python embarque officiel, empreinte verifiee
$pyUrl = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip'
$pySha = '009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b'
$pyZip = Join-Path $Out 'python-3.11.9-embed-amd64.zip'
if (-not (Test-Path $pyZip) -or (Get-FileHash $pyZip -Algorithm SHA256).Hash -ne $pySha) {
  Invoke-WebRequest $pyUrl -OutFile $pyZip -UseBasicParsing
}
if ((Get-FileHash $pyZip -Algorithm SHA256).Hash -ne $pySha) { throw 'Empreinte du Python embarque incorrecte' }
Expand-Archive $pyZip -DestinationPath (Join-Path $stage 'python') -Force

# appli Windows autonome
dotnet publish (Join-Path $root 'app\GoXLRMini.csproj') -c Release -r win-x64 --self-contained true -p:PublishReadyToRun=false -p:DebugType=none -o (Join-Path $stage 'app') --nologo
if ($LASTEXITCODE -ne 0) { throw 'Compilation de l appli echouee' }
Get-ChildItem (Join-Path $stage 'app') -Recurse -Include *.pdb, *.xml | Remove-Item -Force

# moteur, interface, installeur, licences
foreach ($f in 'goxlrctl.py', 'simulator.py', 'ui.html', 'overlay.html', 'profile.json') { Copy-Item (Join-Path $root "engine\$f") $stage }
foreach ($f in 'install.ps1', 'uninstall.ps1', 'Installer.cmd', 'Desinstaller.cmd') { Copy-Item (Join-Path $root "installer\$f") $stage }
Copy-Item (Join-Path $root 'LICENSE') (Join-Path $stage 'LICENSE.txt')
Copy-Item (Join-Path $root 'THIRD-PARTY-NOTICES.md') $stage
$lisez = @("GoXLR Mini $version", '',
  'Installer : double-clic sur Installer.cmd (les droits administrateur sont demandes).',
  'Desinstaller : Desinstaller.cmd, ou Parametres > Applications.',
  'Prerequis : pilote officiel GoXLR (TC-Helicon) installe. Ne pas lancer GoXLR Utility en meme temps.',
  'Code source, aide et nouveautes : https://github.com/samirmedani/goxlr-mini') -join $nl
[IO.File]::WriteAllText((Join-Path $stage 'LISEZMOI.txt'), $lisez + $nl, $utf8)

# manifeste : chaque fichier et son empreinte (l'installeur et la mise a jour copient cette liste)
$commit = ''
try { $commit = (git -C $root rev-parse --short HEAD 2>$null) } catch { }
$files = [ordered]@{}
Get-ChildItem $stage -Recurse -File | Sort-Object FullName | ForEach-Object {
  $rel = $_.FullName.Substring($stage.Length + 1).Replace('\', '/')
  $files[$rel] = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
}
$files['manifest.json'] = ''
$man = [ordered]@{ name = 'GoXLR Mini'; version = $version; release = $true; commit = "$commit"; built = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); files = $files }
[IO.File]::WriteAllText((Join-Path $stage 'manifest.json'), ($man | ConvertTo-Json -Depth 5), $utf8)

# archive (zipfile du Python embarque : chemins en "/", identiques partout)
$zip = Join-Path $Out 'GoXLR-Mini.zip'
if (Test-Path $zip) { Remove-Item $zip -Force }
$code = 'import os,sys,zipfile; s,z=sys.argv[1],sys.argv[2]; f=zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED,compresslevel=9); [f.write(os.path.join(d,n),os.path.relpath(os.path.join(d,n),s).replace(os.sep,"/")) for d,_,ns in os.walk(s) for n in sorted(ns)]; f.close()'
& (Join-Path $stage 'python\python.exe') -c $code $stage $zip
if ($LASTEXITCODE -ne 0) { throw 'Creation de l archive echouee' }
$sha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText((Join-Path $Out 'GoXLR-Mini.sha256'), "$sha  GoXLR-Mini.zip" + [char]10, $utf8)
$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "dist\GoXLR-Mini.zip : $mb Mo, sha256 $sha, $($files.Count) fichiers"
