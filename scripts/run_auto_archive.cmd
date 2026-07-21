@echo off
if exist "%~dp0..\backend\venv\Scripts\python.exe" (
    "%~dp0..\backend\venv\Scripts\python.exe" "%~dp0auto_archive.py" >> "%~dp0auto_archive.log" 2>&1
) else (
    python "%~dp0auto_archive.py" >> "%~dp0auto_archive.log" 2>&1
)
