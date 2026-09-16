# Rodar integração Solides em VM Windows 10 (Proxmox)

Guia para deixar o servidor de integração rodando em uma VM Windows 10 no Proxmox, **ligada o tempo todo** e **iniciando o serviço automaticamente** quando a VM ligar.

---

## 1. Proxmox: VM ligar junto com o host

Para a VM **não ficar desligada** quando o servidor Proxmox reiniciar:

1. No **Proxmox** (interface web), selecione a VM (Windows 10).
2. Vá em **Options** (Opções).
3. Clique em **Start at boot** e marque **Yes**.
4. (Opcional) Ajuste **Startup order** (ex.: 2) e **Startup delay** (ex.: 60 segundos) se tiver várias VMs.

**Pelo terminal no Proxmox:**

```bash
qm set <ID_DA_VM> --onboot 1
```

Substitua `<ID_DA_VM>` pelo ID da sua VM (ex.: 100). Assim a VM sobe automaticamente quando o host Proxmox iniciar.

---

## 2. Na VM Windows 10: preparar o ambiente

### 2.1 Instalar Python

1. Baixe o instalador em [python.org/downloads](https://www.python.org/downloads/).
2. Recomendado: **Python 3.12 ou 3.13**.
3. Evite **Python 3.14** por enquanto: o **Playwright** frequentemente demora para suportar versões muito novas e pode dar erro como `No module named playwright`.
4. Na instalação, marque **"Add Python to PATH"**.
5. Conclua a instalação.

### 2.2 Copiar o projeto para a VM

Copie a pasta do projeto (integração solides) para a VM, por exemplo:

- `C:\IntegracaoSolides\`

Mantenha a mesma estrutura (arquivos `.py`, `.env`, scripts RPA, etc.).

### 2.3 Instalar dependências

Abra **PowerShell** ou **CMD** como administrador, vá até a pasta do projeto e rode:

```cmd
cd C:\IntegracaoSolides
pip install -r requirements.txt
```

Se usar **ambiente virtual** (recomendado):

```cmd
cd C:\IntegracaoSolides
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2.4 Playwright (navegador para os RPAs)

Os scripts RPA usam Playwright. Na mesma pasta do projeto:

```cmd
python -m playwright install
```

Ou, com venv ativado:

```cmd
call venv\Scripts\activate
python -m playwright install
```

### 2.5 Arquivo .env

Confirme que o arquivo **`.env`** está na pasta do projeto na VM com as mesmas variáveis (AD, e-mail, webhook secret, etc.). Sem ele o servidor não conecta no AD nem envia e-mail.

---

## 3. Servidor + ngrok subindo sozinhos na VM (Task Scheduler)

O servidor (`server.py`, via Waitress) e o `ngrok` sobem juntos, disparados pelo **mesmo** `iniciar_servidor_vm.bat`, através de uma Tarefa Agendada já configurada nesta VM chamada **`Integração Solides - server`**.

### 3.1 Como a tarefa está configurada

| Aba | Configuração |
|-----|---------------|
| **Geral** | Executa como `Administrador`, com **"Executar estando o usuário conectado ou não"**, `LogonType: Password` (o Windows guarda a credencial de forma criptografada — não é a mesma coisa que login automático do Windows, que grava a senha em texto claro no Registro) |
| **Disparadores** | **Dois gatilhos**: ao fazer **logon** do usuário `Administrador`, **e** `AtStartup` (na inicialização da VM). Os dois coexistem — cobre tanto o caso de alguém logar quanto o de a VM reiniciar sozinha (update do Windows, queda de energia, manutenção do Proxmox) sem ninguém entrar na tela |
| **Ações** | Programa: `C:\IntegracaoSolides\iniciar_servidor_vm.bat` |

O `.bat` abre duas janelas destacadas (`start "" cmd /c ...`): uma com `python -m waitress --host=0.0.0.0 --port=3000 server:app`, outra com `ngrok http 3000`. Por rodarem via Tarefa Agendada (Sessão 0 do Windows), essas janelas **não aparecem** na área de trabalho mesmo com o processo ativo — não estranhe não ver nada na tela depois de ligar a VM; é esperado.

> **Nunca rode `iniciar_servidor_vm.bat` manualmente enquanto essa tarefa existir.** Isso abriria um segundo processo de `ngrok`, e contas gratuitas só permitem uma sessão de túnel simultânea — a segunda tentativa falha com `ERR_NGROK_108`, e a URL pública que aparecer pode não ser a que está de fato recebendo o tráfego configurado no Solides.

### 3.2 Verificar e reiniciar (PowerShell)

```powershell
# Ver os dois gatilhos configurados
(Get-ScheduledTask -TaskName "Integração Solides - server").Triggers | Select-Object -ExpandProperty CimClass | Select-Object CimClassName
# Deve retornar: MSFT_TaskLogonTrigger e MSFT_TaskBootTrigger

# Ver a credencial/tipo de execução
(Get-ScheduledTask -TaskName "Integração Solides - server").Principal

# Ver a última execução (LastTaskResult 267014 é normal — significa "a tarefa
# encerrou", não erro; o .bat abre as janelas destacadas e termina em seguida,
# enquanto server.py e ngrok continuam rodando por trás)
Get-ScheduledTaskInfo -TaskName "Integração Solides - server"

# Reiniciar o servidor + ngrok sem duplicar processo
Restart-ScheduledTask -TaskName "Integração Solides - server"
# ou
schtasks /run /tn "Integração Solides - server"
```

Se a tarefa ainda não tiver o gatilho de `AtStartup` (por exemplo, numa VM nova clonada desta), adicione assim — mantém o gatilho de logon que já existe:

```powershell
$tarefa = Get-ScheduledTask -TaskName "Integração Solides - server"
$novoTrigger = New-ScheduledTaskTrigger -AtStartup
$todosTriggers = $tarefa.Triggers + $novoTrigger

# Tarefas com LogonType Password exigem reafirmar a credencial ao editar,
# senão dá erro "Nome de usuário ou senha incorretos" (0x8007052e)
$cred = Get-Credential -UserName "Administrador" -Message "Senha da tarefa"
Set-ScheduledTask -TaskName "Integração Solides - server" -Trigger $todosTriggers `
  -User $cred.UserName -Password $cred.GetNetworkCredential().Password
```

### 3.3 Criar a tarefa do zero (VM nova, sem a tarefa ainda)

Se for configurar em uma VM que ainda não tem a tarefa:

1. Abra **Agendador de Tarefas** → **Criar Tarefa** (não "Tarefa Básica").
2. Aba **Geral**: nome `Integração Solides - server`, usuário `Administrador` (ou o que a VM usa), marque **Executar estando o usuário conectado ou não** e **Executar com os privilégios mais altos**.
3. Aba **Disparadores**: adicione **dois** — **Ao fazer logon** (usuário: Administrador) **e** **Na inicialização**.
4. Aba **Ações**: **Iniciar um programa** → `C:\IntegracaoSolides\iniciar_servidor_vm.bat`.
5. Aba **Condições**: desmarque "Iniciar a tarefa somente se o computador estiver conectado à energia CA".
6. Salve — vai pedir a senha do usuário nesse momento (é o que grava a credencial).
7. Teste: `schtasks /run /tn "Integração Solides - server"` e confira `http://localhost:3000/status`.

---

## 4. Programação de férias (tarefa diária às 7h)

A tela **Férias** do painel permite agendar a pausa de acessos durante o período de férias de um colaborador (e a reativação automática no retorno). Isso depende de uma segunda Tarefa Agendada, independente da do servidor: **`Rotina Férias - Acessos`**.

### 4.1 O que ela faz

Roda `tarefa_ferias.py`, que:

- Inativa, nos sistemas escolhidos, quem começa férias no dia;
- Reativa, nos mesmos sistemas em que foi pausado, quem termina férias no dia (ou já passou da data e ainda não foi reativado);
- Em caso de falha em algum sistema, marca para tentar de novo no dia seguinte e inclui no e-mail de resumo enviado ao TI.

Os agendamentos ficam em `data\agendamentos_ferias.json` — não depende de banco de dados.

### 4.2 Como a tarefa está configurada

| Aba | Configuração |
|-----|---------------|
| **Geral** | Mesmo padrão da tarefa do servidor: `Administrador`, "Executar estando o usuário conectado ou não" |
| **Disparadores** | Diário, às **07:00** |
| **Ações** | `C:\IntegracaoSolides\venv\Scripts\python.exe` (ou o `python.exe` do ambiente usado) com argumento `tarefa_ferias.py`, "Iniciar em" `C:\IntegracaoSolides` |

### 4.3 Criar a tarefa do zero (PowerShell)

```powershell
schtasks /create /tn "Rotina Ferias - Acessos" ^
  /tr "cmd /c cd /d C:\IntegracaoSolides && python tarefa_ferias.py >> data\ferias_log.txt 2>&1" ^
  /sc daily /st 07:00 /ru Administrador /rp *
```

(`/rp *` faz o `schtasks` perguntar a senha na hora de criar — não fica em texto claro no comando. Se usar venv, troque `python` pelo caminho completo, ex.: `venv\Scripts\python.exe`.)

### 4.4 Verificar e testar

```powershell
Get-ScheduledTaskInfo -TaskName "Rotina Ferias - Acessos"
(Get-ScheduledTask -TaskName "Rotina Ferias - Acessos").Triggers

# Rodar agora, sem esperar as 7h (útil pra testar um agendamento novo)
schtasks /run /tn "Rotina Ferias - Acessos"
```

O log de cada execução fica em `data\ferias_log.txt` (se a tarefa foi criada com o redirecionamento `>>` do exemplo acima).

---

## 5. Resumo

| O quê | Onde |
|-------|------|
| VM não ficar desligada após reboot do Proxmox | Proxmox → VM → Options → Start at boot = Yes |
| Servidor + ngrok subindo sozinhos | Task Scheduler → `Integração Solides - server` (gatilhos: logon **e** inicialização) executando `iniciar_servidor_vm.bat` |
| Servidor estável (produção) | Usar `waitress` (já é o que o `.bat` faz), não o `flask run` de desenvolvimento |
| Webhook pela internet | `ngrok http 3000`, aberto pelo mesmo `.bat`/tarefa do servidor — não precisa de tarefa separada |
| Pausa/retorno automático de acessos em férias | Task Scheduler → `Rotina Ferias - Acessos` (diária, 07:00) executando `tarefa_ferias.py` |

Assim você deixa a VM Windows 10 no Proxmox ligada e o servidor de integração Solides — junto com o ngrok e a rotina de férias — rodando de forma contínua e automática, mesmo depois de um reinício sem ninguém logar.
