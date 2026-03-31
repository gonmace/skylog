@echo off
cd /d "%~dp0"

echo Instalando dependencias del agente...
pip install -r requirements-agent.txt

echo Compilando agente...
pyinstaller --onefile --noconsole --name redline_agent agent.py

echo Copiando config.json junto al .exe...
copy /Y config.json dist\config.json

echo.
echo Compilacion completada.
echo Archivos listos en la carpeta dist\:
echo   - redline_agent.exe
echo   - config.json  ^<-- edita este con el jwt_token del empleado
echo.
echo Para instalar en inicio de Windows: dist\redline_agent.exe --install
pause
