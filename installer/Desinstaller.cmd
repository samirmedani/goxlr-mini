@echo off
rem Desinstalle GoXLR Mini.
set /p KEEP="Supprimer aussi tes reglages GoXLR Mini ? (o/N) "
if /i "%KEEP%"=="o" (set OPT=-RemoveData) else (set OPT=)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %OPT%
