@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 serve.py
    pause
    exit /b
)
where python >nul 2>nul
if not errorlevel 1 (
    python serve.py
    pause
    exit /b
)
echo.
echo Для сервера нужен Python 3.9 или новее.
echo Без сервера на компьютере можно открыть index.html двойным щелчком.
echo Инструкция для телефона находится в README.md.
pause
