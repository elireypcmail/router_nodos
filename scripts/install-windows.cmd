@echo off
rem Multishop nodo - instalador Windows
rem Clic derecho -> Ejecutar como administrador
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-windows.ps1" %*
set EXITCODE=%ERRORLEVEL%
if %EXITCODE% neq 0 (
    echo.
    echo Instalacion fallida. Revise los mensajes arriba.
    pause
    exit /b %EXITCODE%
)
exit /b 0
