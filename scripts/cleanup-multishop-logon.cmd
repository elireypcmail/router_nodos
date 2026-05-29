@echo off
rem Quita tareas legacy Multishop-Nodo-*-Logon (Program Files = solo ONSTART).
rem Clic derecho -> Ejecutar como administrador
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0cleanup-multishop-logon.ps1" %*
set EXITCODE=%ERRORLEVEL%
if %EXITCODE% neq 0 (
    echo.
    echo Limpieza fallida. Revise los mensajes arriba.
    pause
    exit /b %EXITCODE%
)
pause
exit /b 0
