@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto local_python
py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if not errorlevel 1 goto python_launcher
python scripts\launch_editor.py %*
goto finished
:python_launcher
py -3 scripts\launch_editor.py %*
goto finished
:local_python
".venv\Scripts\python.exe" scripts\launch_editor.py %*
:finished
set "OC_EDITOR_RESULT=%errorlevel%"
if not "%OC_EDITOR_RESULT%"=="0" pause
exit /b %OC_EDITOR_RESULT%
