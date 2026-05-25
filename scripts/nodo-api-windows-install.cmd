@echo off
rem Multishop nodo - autostart API (tareas + ProgramData)
rem Clic derecho -> Ejecutar como administrador
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0nodo-api-windows-install.ps1" %*
set EXITCODE=%ERRORLEVEL%
if %EXITCODE% neq 0 (
    echo.
    echo Registro API fallido. Ejecute como administrador.
    pause
    exit /b %EXITCODE%
)
exit /b 0
