@echo off
cd /d "%~dp0"

echo Instalando dependencias del agente...
pip install -r requirements-agent.txt

echo Compilando agente...
pyinstaller redline_agent.spec --noconfirm

echo.
echo Compilacion completada.
echo Ejecutable listo en: dist\redline_agent.exe
echo.
echo Para instalar en inicio de Windows: dist\redline_agent.exe --install
pause
