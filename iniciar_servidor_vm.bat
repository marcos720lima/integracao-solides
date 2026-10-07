@echo off
title Servidor Integracao Solides - VM
cd /d "%~dp0"

REM Se usar ambiente virtual, descomente a linha abaixo e ajuste o caminho:
call venv\Scripts\activate

REM So inicia o servidor se ainda nao tiver um rodando (evita servidores duplicados na porta 3000)
set RODANDO=0
for /f %%N in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*waitress*' } | Measure-Object).Count"') do set RODANDO=%%N
if "%RODANDO%"=="0" (
    echo Iniciando servidor ^(Waitress - producao^) em nova janela...
    start "" cmd /c "cd /d %~dp0 && python -m waitress --host=0.0.0.0 --port=3000 server:app"
) else (
    echo Servidor ja esta rodando ^(%RODANDO% processo^(s^)^) - nao vou abrir outro.
)

REM So inicia o ngrok se ainda nao tiver um rodando (a conta gratuita aceita um tunel so)
tasklist /FI "IMAGENAME eq ngrok.exe" | find /I "ngrok.exe" >nul
if errorlevel 1 (
    echo Iniciando ngrok em nova janela...
    start "" cmd /c "cd /d %~dp0 && ngrok http 3000"
) else (
    echo ngrok ja esta rodando - nao vou abrir outro.
)

pause
