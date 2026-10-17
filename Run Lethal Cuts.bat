@echo off
rem Starts Lethal Cuts from the source code (for testing before the installer exists).
cd /d "%~dp0"
start "" pythonw -m lethal_cuts %*
