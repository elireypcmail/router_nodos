@echo off
rem Multishop nodo - desinstalador Windows
rem Clic derecho -> Ejecutar como administrador
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall-windows.ps1" %*
set EXITCODE=%ERRORLEVEL%
if %EXITCODE% neq 0 (
    echo.
    echo Desinstalacion fallida o incompleta. Revise los mensajes arriba.
    pause
    exit /b %EXITCODE%
)
echo.
pause
exit /b 0
