@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Install the project as described in README.md first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run dashboard/app.py
