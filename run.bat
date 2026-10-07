@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    py -3.11 -m venv .venv || py -3 -m venv .venv || (echo Python 3.11+ is required & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
python run_fileflow.py
