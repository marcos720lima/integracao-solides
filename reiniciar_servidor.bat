@echo off
chcp 65001 >nul
title Reiniciar servidor - Gestao de Identidade e Acesso
set TAREFA=Integracao Solides - server

echo.
echo === Reiniciando o servidor do painel ===
echo.

echo [1/5] Parando a tarefa agendada "%TAREFA%"...
schtasks /End /TN "%TAREFA%" >nul 2>&1

echo [2/5] Encerrando os servidores do painel (waitress)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*waitress*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*waitress*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

for /f %%N in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*waitress*' }).Count"') do set SOBROU=%%N
if not "%SOBROU%"=="0" (
    echo.
    echo [ERRO] Ainda tem %SOBROU% processo^(s^) do servidor rodando. Rode este .bat como administrador.
    pause
    exit /b 1
)

echo [3/5] Encerrando o ngrok...
taskkill /F /IM ngrok.exe >nul 2>&1

echo [4/5] Iniciando a tarefa agendada...
schtasks /Run /TN "%TAREFA%" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERRO] Nao consegui iniciar a tarefa "%TAREFA%". Rode este .bat como administrador.
    pause
    exit /b 1
)

echo [5/5] Aguardando subir (15s)...
timeout /t 15 /nobreak >nul

for /f %%N in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*waitress*' }).Count"') do set PY=%%N
for /f %%N in ('powershell -NoProfile -Command "(Get-Process ngrok -ErrorAction SilentlyContinue | Measure-Object).Count"') do set NG=%%N

echo.
echo === Resultado ===
echo Processos do servidor: %PY%  (o normal e 2: venv + python)
echo Processos do ngrok:    %NG%  (o normal e 1)
echo.
if "%PY%"=="0" echo [ATENCAO] O servidor nao subiu. Veja a tarefa no Agendador.
if "%NG%"=="0" echo [ATENCAO] O ngrok nao subiu. Os webhooks da Solides nao vao chegar.
if %PY% GTR 2 echo [ATENCAO] Tem mais de um servidor rodando. Rode este .bat de novo.
echo Painel do ngrok: http://127.0.0.1:4040
echo.
pause