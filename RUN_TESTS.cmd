@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0BUILD_AND_TEST.ps1" %*
