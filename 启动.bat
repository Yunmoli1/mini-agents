@echo off
rem ASCII-only launcher shell: all Chinese guidance lives in scripts/launcher.py
rem (batch files must never contain non-ASCII text - cmd parses them as ANSI/GBK)
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.10+ from python.org first.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
".venv\Scripts\python.exe" scripts\launcher.py %*
pause
