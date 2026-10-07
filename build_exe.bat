@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    py -3.11 -m venv .venv || py -3 -m venv .venv || (echo Python 3.11+ is required & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-dev.txt || exit /b 1
echo Running tests...
python -m unittest discover -s tests -t . || (echo Tests failed - not building & exit /b 1)
pyinstaller --noconfirm --clean --windowed --name FileFlow --collect-submodules fileflow --collect-all imagehash run_fileflow.py || exit /b 1
echo.
echo Built: dist\FileFlow\FileFlow.exe   (zip the dist\FileFlow folder to share it)
echo For a single-file EXE add --onefile to the pyinstaller line (slower start-up).
