@echo off
chcp 65001 >nul
title Reiniciar servidor - Gestao de Identidade e Acesso
set TAREFA=Integracao Solides - server
set URL_STATUS=http://127.0.0.1:3000/status
set ESPERA_MAXIMA=60

echo.
echo === Reiniciando o servidor do painel ===
echo.

echo [1/5] Parando a tarefa agendada "%TAREFA%"...
schtasks /End /TN "%TAREFA%" >nul 2>&1

echo [2/5] Encerrando os servidores do painel (waitress)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*waitress*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*waitress*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

set SOBROU=0
for /f %%N in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*waitress*' } | Measure-Object).Count"') do set SOBROU=%%N
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

echo [5/5] Esperando o servidor responder (ate %ESPERA_MAXIMA%s)...
set SEGUNDOS=0
:esperar
set CODIGO=000
for /f %%C in ('curl -s -o nul -w "%%{http_code}" --max-time 3 %URL_STATUS% 2^>nul') do set CODIGO=%%C
if "%CODIGO%"=="200" goto subiu
if %SEGUNDOS% GEQ %ESPERA_MAXIMA% goto nao_subiu
timeout /t 2 /nobreak >nul
set /a SEGUNDOS+=2
goto esperar

:subiu
set NG=0
for /f %%N in ('powershell -NoProfile -Command "(Get-Process ngrok -ErrorAction SilentlyContinue | Measure-Object).Count"') do set NG=%%N
echo.
echo === Resultado ===
echo [OK] Servidor respondendo em %URL_STATUS% (subiu em ~%SEGUNDOS%s)
if "%NG%"=="0" (
    echo [ATENCAO] O ngrok nao subiu. Os webhooks da Solides nao vao chegar.
) else (
    echo [OK] ngrok rodando. Painel do ngrok: http://127.0.0.1:4040
)
echo.
pause
exit /b 0

:nao_subiu
echo.
echo === Resultado ===
echo [ATENCAO] O servidor nao respondeu em %ESPERA_MAXIMA%s.
echo Veja a tarefa "%TAREFA%" no Agendador e a tela de Logs / logs\integracao_solides.log.
echo.
pause
exit /b 1
