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

## 3. Servidor iniciando sozinho na VM (Task Scheduler)

Para o servidor **subir automaticamente** quando alguém logar na VM (ou quando a VM ligar, se configurar logon automático):

### 3.1 Usar o script em batch (Waitress – produção)

Foi criado o arquivo **`iniciar_servidor_vm.bat`**. Ele sobe o servidor com **Waitress** (servidor WSGI adequado para produção), na porta 3000.

Se a pasta do projeto na VM for outra (ex.: `C:\IntegracaoSolides`), edite o `.bat` ou crie um atalho que execute:

```cmd
cd /d C:\IntegracaoSolides
python -m waitress --host=0.0.0.0 --port=3000 server:app
```

Se usar venv:

```cmd
cd /d C:\IntegracaoSolides
call venv\Scripts\activate
python -m waitress --host=0.0.0.0 --port=3000 server:app
```

### 3.2 Agendar no Task Scheduler (início ao logon)

1. Abra **Agendador de Tarefas** (Task Scheduler).
2. **Criar Tarefa** (não “Tarefa Básica”).
3. Aba **Geral**:
   - Nome: ex. `Integracao Solides - Servidor`
   - Marque **Executar estando o usuário conectado ou não** e **Executar com privilégios mais altos** se precisar.
   - Configure para executar com o usuário que faz logon na VM.
4. Aba **Disparadores**:
   - **Novo** → **Iniciar a tarefa**: **Ao fazer logon** (ou **Na inicialização** se a VM tiver logon automático).
   - Usuário: o usuário que usa a VM.
5. Aba **Ações**:
   - **Novo** → **Iniciar um programa**.
   - Programa: `C:\IntegracaoSolides\iniciar_servidor_vm.bat` (ajuste o caminho).
   - Ou use:
     - Programa: `C:\Windows\System32\cmd.exe`
     - Argumentos: `/c "cd /d C:\IntegracaoSolides && venv\Scripts\activate && python -m waitress --host=0.0.0.0 --port=3000 server:app"`
   - Iniciar em: `C:\IntegracaoSolides`.
6. Aba **Condições**: desmarque **Iniciar a tarefa somente se o computador estiver conectado à energia CA** se for VM sempre ligada.
7. Salve e teste: faça logoff/logon ou reinicie a VM e verifique se o servidor está respondendo em `http://localhost:3000/status`.

Assim, sempre que a VM estiver ligada e o usuário logado (ou na inicialização, conforme configurado), o servidor sobe sozinho.

---

## 4. Ngrok (se os webhooks vêm da internet)

Se o Solides envia webhook para uma URL pública (ngrok):

- O ngrok precisa estar rodando **na mesma VM** e apontando para `http://localhost:3000`.
- Você pode:
  - Colocar o **ngrok** em outra tarefa agendada (outro disparador “Ao fazer logon”), ou
  - Incluir no mesmo `.bat` a abertura do ngrok (em uma janela separada ou em background), ou
  - Usar o **ngrok como serviço** no Windows (ex.: com NSSM) para subir junto com a VM.

Exemplo de comando ngrok (ajuste o binário e a região se precisar):

```cmd
ngrok http 3000
```

A URL pública que o ngrok mostrar é a que você configura no Solides como URL do webhook.

---

## 5. Resumo

| O quê | Onde |
|-------|------|
| VM não ficar desligada após reboot do Proxmox | Proxmox → VM → Options → Start at boot = Yes |
| Servidor subir sozinho na VM | Task Scheduler → tarefa “Ao fazer logon” executando `iniciar_servidor_vm.bat` (ou comando waitress) |
| Servidor estável (produção) | Usar `waitress` (script `.bat` ou comando acima), não o `flask run` de desenvolvimento |
| Webhook pela internet | Ngrok (ou túnel similar) rodando na VM, em tarefa separada ou como serviço |

Assim você deixa a VM Windows 10 no Proxmox ligada e o servidor de integração Solides rodando de forma contínua e automática.
