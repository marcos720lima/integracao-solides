@echo off
title Servidor Integracao Solides
cd /d "%~dp0"

REM Se usar ambiente virtual, descomente a linha abaixo e ajuste o caminho:
REM call .venv\Scripts\activate
REM call venv\Scripts\activate

echo Iniciando servidor (Waitress - producao)...
python -m waitress --host=0.0.0.0 --port=3000 server:app

pause
