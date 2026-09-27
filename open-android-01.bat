@echo off
title Launching Redroid Account 01
cd /d "%~dp0"
echo Starting Redroid Android 01 instance...
powershell -ExecutionPolicy Bypass -File .\redroid.ps1 start 01
echo Launching Scrcpy display window...
powershell -ExecutionPolicy Bypass -File .\redroid.ps1 scrcpy 01
