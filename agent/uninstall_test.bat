@echo off
echo Desinstalando RedLine GS Agent...

taskkill /F /IM redline_agent.exe 2>nul

if exist "%ProgramFiles%\RedLineGS\unins000.exe" (
    "%ProgramFiles%\RedLineGS\unins000.exe" /SILENT
    timeout /t 3 /nobreak >nul
) else (
    echo Instalador no encontrado, limpiando manualmente...
    rmdir /S /Q "%ProgramFiles%\RedLineGS" 2>nul
    reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "RedLine GS Agent" /f 2>nul
)

rmdir /S /Q "%APPDATA%\RedLineGS" 2>nul

echo Listo. El equipo queda como nuevo.
pause
