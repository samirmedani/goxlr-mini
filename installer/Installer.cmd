@echo off
rem Installe ou met a jour GoXLR Mini (les droits administrateur sont demandes).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
