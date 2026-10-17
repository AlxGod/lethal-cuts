@echo off
rem Builds the installer and the handoff zip into the dist folder.
cd /d "%~dp0"
python packaging\build.py
pause
