# Integração Solides - Active Directory + Sistemas

Sistema automatizado que recebe webhooks do Solides quando um colaborador é demitido e executa:

- ✅ Desativa o usuário no **Active Directory**
- ✅ Desativa no **CRM JMJ**
- ✅ Desativa no **SAW**
- ✅ Desativa no **GIU Unimed**
- ✅ Bloqueia no **GED Bye Bye Paper**
- ✅ Desativa no **B+ Reembolso**
- ✅ Desativa no **Tasy EMR**
- ✅ Suspende no **Google Workspace** (opcional)
- ✅ Envia **email de notificação** para o TI
- ✅ **Inativação parcial** quando usuário não encontrado no AD
- ✅ **Logs automáticos** com rotação

> Observação: **NextQS Manager está desativado no processo atualmente** (não é executado).

## Tecnologias Utilizadas

| Tecnologia | Versão | Descrição |
|------------|--------|-----------|
| **Python** | 3.11+ | Linguagem principal |
| **Flask** | 3.1.2 | Framework web para API REST |
| **Flask-CORS** | 4.0.0 | Suporte a Cross-Origin Resource Sharing |
| **LDAP3** | 2.9.1 | Conexão com Active Directory |
| **Playwright** | 1.40.0 | Automação de navegador (RPA) |
| **python-dotenv** | 1.0.0 | Gerenciamento de variáveis de ambiente |
| **Requests** | 2.32.5 | Cliente HTTP |
| **ngrok** | - | Túnel para expor servidor local |
| **SMTP** | - | Envio de emails de notificação |

### Arquitetura

- **Backend:** API REST com Flask
- **Integração AD:** Protocolo LDAP sobre SSL (LDAPS)
- **RPA:** Playwright com Chromium headless
- **Webhooks:** Recebimento de eventos do Solides
- **Notificações:** Email via SMTP (Gmail)

## Fluxo

```
Solides → Webhook → ngrok → Servidor Local → AD + Google Workspace + CRM + SAW + GIU + GED + NextQS + B+ + Email

> Observação: **NextQS não é executado** no momento.
```

## Instalação (ambiente local ou VM)

```bash
# Criar ambiente virtual (recomendado Python 3.12 ou 3.13)
python -m venv venv
venv\Scripts\activate

# Atualizar ferramentas básicas
python -m pip install -U pip setuptools wheel

# Instalar dependências
python -m pip install -r requirements.txt

# Instalar Playwright (navegador para RPA)
python -m playwright install
```

## Configuração

### 1. Criar arquivo `.env`

Copie o `env.example` para `.env` e preencha com suas credenciais:

```env
# Active Directory
AD_URL=ldaps://seu-servidor-ad:636
AD_USER=CN=Usuario,OU=TI,DC=empresa,DC=com
AD_PASS=sua-senha
BASE_DN=DC=empresa,DC=com

# Email (Gmail - usar senha de app)
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_USERNAME=seu-email@empresa.com
EMAIL_PASSWORD=xxxx xxxx xxxx xxxx

# Destinatários (separados por vírgula)
TI_EMAILS=ti@empresa.com

# Webhook
WEBHOOK_SECRET=sua-chave-secreta

# Logs (opcional - se não definir, usa padrão do sistema)
LOG_MAX_BYTES=5242880
LOG_BACKUP_COUNT=10
DESLIGAMENTOS_CSV=C:\IntegracaoSolides\data\desligamentos_historico.csv

# Google Workspace Admin (opcional - fluxo de demissão)
GOOGLE_ADMIN_ENABLED=false
GOOGLE_SERVICE_ACCOUNT_FILE=C:\secure\google\service-account.json
GOOGLE_DELEGATED_ADMIN=admin@empresa.com.br
GOOGLE_WORKSPACE_DOMAIN=empresa.com.br

# CRM JMJ
CRM_URL=https://seu-crm.jmjsistemas.com.br/crm
CRM_USERNAME=usuario
CRM_PASSWORD=senha

# SAW
SAW_URL=https://saw.trixti.com.br/saw
SAW_USERNAME=usuario
SAW_PASSWORD=senha

# GIU Unimed (login com CPF do admin)
GIU_URL=https://giu.unimed.coop.br
GIU_USERNAME=000.000.000-00
GIU_PASSWORD=sua-senha

# GED Bye Bye Paper
GED_URL=https://app.gedbyebyepaper.com.br
GED_CONTA=GED0000000
GED_USERNAME=usuario
GED_PASSWORD=senha

# NextQS Manager (desativado atualmente no processo)
NEXTQS_URL=https://manager.nextqs.com
NEXTQS_USERNAME=seu-email@empresa.com
NEXTQS_PASSWORD=sua-senha

# B+ Reembolso
BPLUS_URL=https://bplus.unimedoestedopara.coop.br
BPLUS_USERNAME=usuario
BPLUS_PASSWORD=senha
```

### 2. Instalar ngrok

```bash
winget install ngrok.ngrok
ngrok config add-authtoken SEU_TOKEN
```

### 3. Integração Google Workspace (opcional - somente demissão)

Se quiser suspender automaticamente o email do colaborador demitido no Google Workspace:

1. Crie/baixe a Service Account JSON e guarde em caminho seguro (fora do repositório).
2. Ative **Domain-Wide Delegation** na Service Account.
3. No Admin Console Google, adicione o **Client ID** da Service Account em:
   - Security > API controls > Domain-wide delegation
4. Autorize os scopes:
   - `https://www.googleapis.com/auth/admin.directory.user.readonly` (teste/leitura)
   - `https://www.googleapis.com/auth/admin.directory.user` (suspensão)
5. Configure no `.env`:

```env
GOOGLE_ADMIN_ENABLED=true
GOOGLE_SERVICE_ACCOUNT_FILE=C:\secure\google\service-account.json
GOOGLE_DELEGATED_ADMIN=admin@empresa.com.br
GOOGLE_WORKSPACE_DOMAIN=empresa.com.br
```

Regras aplicadas no fluxo:

- Se não houver email do colaborador, o Google é **pulado** e o processo continua.
- Se o email do colaborador for igual ao admin delegado, o Google é **pulado**.
- Se ocorrer erro no Google, os demais sistemas continuam normalmente.
- Esta integração é usada no fluxo de demissão.

Teste rápido de autenticação (PowerShell):

```powershell
python -c "from dotenv import load_dotenv; load_dotenv('.env'); from google.oauth2 import service_account; from googleapiclient.discovery import build; import os; f=os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE'); a=os.getenv('GOOGLE_DELEGATED_ADMIN'); scopes=['https://www.googleapis.com/auth/admin.directory.user.readonly']; creds=service_account.Credentials.from_service_account_file(f, scopes=scopes).with_subject(a); svc=build('admin','directory_v1',credentials=creds,cache_discovery=False); resp=svc.users().get(userKey=a).execute(); print('OK Google Admin:', resp.get('primaryEmail'))"
```

## Execução (ambiente local)

### 1. Iniciar servidor (desenvolvimento)
```bash
python server.py
```

### 2. Iniciar ngrok (outro terminal)
```bash
ngrok http 3000
```

### 3. Configurar no Solides

| Campo | Valor |
|-------|-------|
| URL | `https://SUA-URL.ngrok-free.app/webhook/solides` |
| Evento | `demissao_colaborador` |
| Header | `X-Webhook-Secret` |
| Valor | sua chave do .env |

---

## Execução em VM Windows 10 (Proxmox)

Para um passo a passo completo (instalar Python, venv, Playwright, Proxmox, Agendador de Tarefas), veja o arquivo `VM_WINDOWS.md`.

### 1. Preparar ambiente na VM (resumo)

```cmd
cd C:\IntegracaoSolides
python -m venv venv
call venv\Scripts\activate.bat
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt
python -m playwright install
```

Certifique-se de copiar o `.env` para a pasta do projeto na VM.

### 2. Subir servidor + ngrok com o .bat

Na VM, após instalar o `ngrok` e configurar o `authtoken`:

```cmd
cd C:\IntegracaoSolides
iniciar_servidor_vm.bat
```

Esse script:

- Abre uma janela com o servidor (Waitress) em `http://localhost:3000`
- Abre outra janela com `ngrok http 3000`

Use a URL pública mostrada pelo ngrok (ex.: `https://xxxx.ngrok-free.app`) para configurar o webhook no Solides:

- URL: `https://xxxx.ngrok-free.app/webhook/solides`
- Header: `X-Webhook-Secret` = mesmo valor do `.env`

## Estrutura

```
├── server.py              # Servidor Flask principal
├── inativar_manual.py     # Script para inativação manual (contingência)
├── rpa_crm.py             # RPA - CRM JMJ (email)
├── rpa_saw.py             # RPA - SAW (email)
├── rpa_giu.py             # RPA - GIU Unimed (CPF)
├── rpa_ged.py             # RPA - GED Bye Bye Paper (email)
├── rpa_nextqs.py          # RPA - NextQS Manager (desativado)
├── rpa_bplus.py           # RPA - B+ Reembolso (nome de conta)
├── rpa_tasy.py            # RPA - Tasy EMR (nome completo + nome de conta)
├── inspecionar_pagina.py  # Ferramenta para mapear novos sites
├── logs/                  # Pasta de logs (criada automaticamente)
│   ├── integracao_solides.log  # Log geral
│   └── webhooks.log            # Log de webhooks
├── env.example            # Template de variáveis
├── requirements.txt       # Dependências Python
├── POP_INTEGRACAO_SOLIDES.md  # Procedimento Operacional Padrão
└── README.md              # Documentação
```

## Endpoints

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/status` | GET | Status do servidor |
| `/webhook/solides` | POST | Recebe webhook de demissão |
| `/consulta-ad` | POST | Consulta usuário no AD |
| `/sistemas/status` | GET | Status dos sistemas RPA |

## Sistemas Integrados

| Sistema | Script | Identificador | Ação |
|---------|--------|---------------|------|
| Active Directory | - | CPF | Desativa conta |
| Google Workspace (opcional) | `google_admin.py` | Email | Suspende conta |
| CRM JMJ | `rpa_crm.py` | Email | Desativa usuário |
| SAW | `rpa_saw.py` | Email | Desativa usuário |
| GIU Unimed | `rpa_giu.py` | CPF | Desativa conta |
| GED Bye Bye Paper | `rpa_ged.py` | Email (busca por nome) | Bloqueia usuário |
| NextQS Manager | `rpa_nextqs.py` | Email | **Desativado no processo** |
| B+ Reembolso | `rpa_bplus.py` | Nome de conta (ex: douglas.barreto) | Inativa usuário |
| Tasy EMR | `rpa_tasy.py` | Nome completo + nome de conta | Inativa usuário |

## Email de Notificação

```
NOTIFICAÇÃO: Colaborador Demitido - Nome

Informações do Colaborador
├── Nome, CPF, Email
├── Setor, Cargo, Matrícula
└── Data Demissão

Inativações Realizadas
├── AD (Active Directory): Desativado
├── Google Workspace:      Suspenso
├── CRM JMJ:               Desativado
├── SAW:                   Desativado
├── GIU Unimed:            Desativado
├── GED (Bye Bye Paper):   Bloqueado
├── NextQS Manager:        Não executado
├── B+ Reembolso:          Inativado
└── Tasy EMR:              Inativado

Ações Recomendadas
├── Revogar acessos VPN
├── Verificar outros sistemas
└── Recolher equipamentos
```

## Proteção contra Duplicatas

O sistema bloqueia o mesmo CPF por **5 minutos** para evitar processamento duplicado.

## Inativação Parcial (Usuário não encontrado no AD)

Quando o usuário não é encontrado no Active Directory, o sistema:

1. Continua a inativação nos sistemas que usam **somente CPF** (ex: GIU)
2. Pula os sistemas que precisam de dados do AD (email, nome)
3. Envia email de notificação normalmente (com status "Não encontrado no AD")

## Inativação Manual (Contingência)

Quando o fluxo automático falhar, use o script de inativação manual:

```bash
# Inativar em todos os sistemas + enviar email
python inativar_manual.py --cpf 01234567890 --email joao.silva@empresa.com.br --nome "JOAO DA SILVA" --enviar-email

# Pular o AD (quando usuário não existe no AD)
python inativar_manual.py --cpf 01234567890 --email joao.silva@empresa.com.br --nome "JOAO DA SILVA" --pular-ad --enviar-email

# Apenas sistemas específicos
python inativar_manual.py --cpf 01234567890 --sistemas giu
python inativar_manual.py --email joao.silva@empresa.com.br --sistemas crm saw ged
```

### Parâmetros disponíveis

| Parâmetro | Descrição |
|-----------|-----------|
| `--cpf` | CPF do colaborador (usado no AD e GIU) |
| `--email` | Email corporativo (usado nos demais sistemas) |
| `--nome` | Nome completo (necessário para Tasy) |
| `--sistemas` | Lista de sistemas: `ad`, `crm`, `saw`, `giu`, `ged`, `bplus`, `tasy` |
| `--pular-ad` | Não tentar desativar no Active Directory |
| `--enviar-email` | Enviar email de notificação para o TI |

## Logs

Os logs são salvos automaticamente na pasta `logs/` com rotação:

| Arquivo | Conteúdo |
|---------|----------|
| `integracao_solides.log` | Log geral de todas as operações |
| `webhooks.log` | Log detalhado dos webhooks recebidos |
| `data/desligamentos_historico.csv` | Histórico permanente de desligamentos (não rotaciona) |

**Características:**
- Rotação automática: 5MB por arquivo, mantém 10 backups
- Formato: `2026-02-04 14:30:25 | INFO | [WEBHOOK] Mensagem...`
- CSV permanente com: colaborador, CPF, email, matrícula, setor, cargo, data de desligamento e status de processamento

**Configuração opcional via `.env`:**
- `LOG_MAX_BYTES`: tamanho máximo de cada arquivo de log em bytes (padrão: `5242880`)
- `LOG_BACKUP_COUNT`: quantidade de backups por log rotacionado (padrão: `10`)
- `DESLIGAMENTOS_CSV`: caminho completo do CSV permanente de desligamentos

**Consultar logs (PowerShell):**
```powershell
# Últimas 50 linhas
Get-Content logs\integracao_solides.log -Tail 50

# Buscar por CPF
Select-String -Path logs\*.log -Pattern "12345678900"

# Buscar erros
Select-String -Path logs\integracao_solides.log -Pattern "ERROR"

# Últimos 10 desligamentos no CSV permanente
Get-Content data\desligamentos_historico.csv -Tail 10
```

## Criando RPA para Novos Sites

Use o script de inspeção para mapear elementos de novos sistemas:

```bash
python inspecionar_pagina.py https://novo-sistema.com/login
```

O gravador captura cliques e digitação, gerando o código automaticamente.

---

**Desenvolvido por:** Marcos Vinicius Viana Lima  
**Versão:** 2.6

