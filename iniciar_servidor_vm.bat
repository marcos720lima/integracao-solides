@echo off
title Servidor Integracao Solides - VM
cd /d "%~dp0"

REM Se usar ambiente virtual, descomente a linha abaixo e ajuste o caminho:
REM call venv\Scripts\activate

echo Iniciando servidor (Waitress - producao) em nova janela...
start "" cmd /c "cd /d %~dp0 && python -m waitress --host=0.0.0.0 --port=3000 server:app"

echo Iniciando ngrok em nova janela...
start "" cmd /c "cd /d %~dp0 && ngrok http 3000"

pause
