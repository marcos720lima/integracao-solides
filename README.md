# Integração Solides - Active Directory + Sistemas + Painel Web

Sistema automatizado que recebe webhooks do Solides quando um colaborador é demitido, além de um **painel web** para gestão manual do dia a dia de TI (colaboradores, Active Directory, Google Workspace, Infomed, e ativação/inativação manual).

## Fluxo automático (webhook de demissão)

Quando o Solides envia o webhook de demissão, o sistema:

- ✅ Desativa o usuário no **Active Directory**
- ✅ Desativa no **CRM JMJ**
- ✅ Desativa no **SAW**
- ✅ Desativa no **GIU Unimed**
- ✅ Bloqueia no **GED Bye Bye Paper**
- ✅ Desativa no **Tasy EMR**
- ✅ Desativa no **Infomed**
- ✅ Suspende no **Google Workspace** (opcional)
- ✅ Envia **email de notificação** para o TI
- ✅ **Inativação parcial** quando usuário não encontrado no AD
- ✅ **Logs automáticos** com rotação
- ✅ **Proteção contra duplicata persistente** — não reprocessa o mesmo desligamento nem que o webhook chegue de novo horas/dias depois

> **NextQS Manager está desativado no processo** — a tela de login usa verificação Cloudflare Turnstile, que bloqueia automação de navegador. Alternativas em avaliação: API oficial do fornecedor ou liberação de IP.
>
> **B+ Reembolso (`rpa_bplus.py`) existe no repositório mas não está ligado a nenhum fluxo** (nem automático, nem manual) — o script foi escrito mas nunca chegou a ser registrado no `SISTEMAS_CONFIG` do `server.py`. Se for pra usar, precisa ser adicionado lá.

## Painel Web

Além do webhook automático, o projeto tem um **painel web** (Flask, acessível via navegador, login com conta do AD com "TI" na descrição) para o time de TI gerenciar tudo manualmente, sem precisar de linha de comando:

| Tela | O que faz |
|------|-----------|
| **Dashboard** | Total de desligados, gráfico por setor, exportar Excel, histórico com busca/filtro |
| **Colaboradores** | Lista do Tangerino (busca por nome ou CPF), card por pessoa com Informações, Horário (logon hours + predefinição de horário administrativo), Senha, Bloqueio e **Sistemas** (status ao vivo em AD, Google, CRM, SAW, GIU, GED, Tasy e Infomed, incluindo o login/código de cada um) |
| **Criar acesso** | Cadastro de novo colaborador: busca no Tangerino por CPF, cria no AD e no Google Workspace |
| **Active Directory** | Busca/filtra usuários do AD (nome, status, setor), com paginação e edição de horário de logon — cobre contas sem CPF vinculado (antigas ou genéricas) que não aparecem em Colaboradores |
| **Google Workspace** | Usuários, grupos de email (com membros) e unidades organizacionais |
| **Infomed** | Busca direta no banco Oracle do Infomed: ativar/inativar usuário, editar dados (nome/email), gerenciar perfis vinculados, corrigir preferências (expiração de senha, tentativas de login) |
| **Férias** | Consulta de férias no Tangerino, com filtro por período/status |
| **Ativação/Inativação manual** | Alternativa manual ao webhook — toggle Ativar/Inativar, escolhe os sistemas, dispara em paralelo. Usado tanto em contingência (webhook falhou) quanto pra reverter uma inativação feita por engano ou reativar alguém voltando de férias |
| **Webhooks** | Inspeciona webhooks recebidos, reprocessa manualmente |
| **Logs** | Visualização dos logs do sistema |

## Tecnologias Utilizadas

| Tecnologia | Versão | Descrição |
|------------|--------|-----------|
| **Python** | 3.11+ | Linguagem principal |
| **Flask** | 3.1.2 | Framework web para API REST e painel |
| **Flask-CORS** | 4.0.0 | Suporte a Cross-Origin Resource Sharing |
| **LDAP3** | 2.9.1 | Conexão com Active Directory |
| **Playwright** | 1.40.0+ | Automação de navegador (RPA) |
| **oracledb** | - | Conexão direta com o banco Oracle do Infomed |
| **python-dotenv** | 1.0.0 | Gerenciamento de variáveis de ambiente |
| **Requests** | 2.32.5 | Cliente HTTP |
| **Waitress** | 3.0.0 | Servidor WSGI de produção |
| **ngrok** | - | Túnel para expor servidor local |
| **SMTP** | - | Envio de emails de notificação |

### Arquitetura

- **Backend:** API REST com Flask + blueprint do painel web (`painel/`)
- **Integração AD:** Protocolo LDAP sobre SSL (LDAPS)
- **Integração Infomed:** Conexão direta ao banco Oracle (via `oracledb`, sem passar pela interface do sistema)
- **RPA:** Playwright com Chromium (CRM, SAW, GIU, GED, Tasy)
- **Webhooks:** Recebimento de eventos do Solides
- **Notificações:** Email via SMTP (Gmail)

## Fluxo

```
Solides → Webhook → ngrok → Servidor Local → AD + Google Workspace + CRM + SAW + GIU + GED + Tasy + Infomed + Email
```

> NextQS e B+ Reembolso não fazem parte do fluxo atualmente (ver observações acima).

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

# Google Workspace Admin (opcional - fluxo de demissão e painel)
GOOGLE_ADMIN_ENABLED=false
GOOGLE_SERVICE_ACCOUNT_FILE=C:\secure\google\service-account.json
GOOGLE_DELEGATED_ADMIN=admin@empresa.com.br
GOOGLE_WORKSPACE_DOMAIN=empresa.com.br

# Tangerino (painel - Colaboradores, Férias, Criar acesso)
TANGERINO_AUTH=Basic xxxxxxxxxxxxxxxxxxxxxxxxxxxxx

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

# Tasy EMR
TASY_URL=https://tasy.unimedoestedopara.coop.br
TASY_USERNAME=usuario
TASY_PASSWORD=senha

# Infomed (Oracle) - ver opções A/B completas no env.example
INFOMED_DB_USER=
INFOMED_DB_PASSWORD=
INFOMED_DB_SCHEMA=API
INFOMED_DB_HOST=
INFOMED_DB_PORT=1521
INFOMED_DB_SERVICE=
# alternativa: INFOMED_DB_DSN + INFOMED_TNS_ADMIN (usa o alias do tnsnames.ora)
# se der erro DPY-3015 (senha em formato antigo): INFOMED_ORACLE_CLIENT_DIR

# NextQS Manager (não executado no fluxo - bloqueado por Cloudflare Turnstile)
NEXTQS_URL=https://manager.nextqs.com
NEXTQS_USERNAME=seu-email@empresa.com
NEXTQS_PASSWORD=sua-senha
```

### 2. Instalar ngrok

```bash
winget install ngrok.ngrok
ngrok config add-authtoken SEU_TOKEN
```

### 3. Integração Google Workspace (opcional)

Se quiser suspender automaticamente o email do colaborador demitido no Google Workspace (e/ou usar a tela de Google Workspace no painel):

1. Crie/baixe a Service Account JSON (Deve ser criado no Cloud Console) e guarde em caminho seguro (fora do repositório).
2. Ative **Domain-Wide Delegation** na Service Account e também o serviço Admin SDK Api na Biblioteca de APIs.
3. No Admin Console Google, adicione o **Client ID** da Service Account em:
   - Security > API controls > Domain-wide delegation
4. Autorize os scopes:
   - `https://www.googleapis.com/auth/admin.directory.user` (usuários - leitura e suspensão)
   - `https://www.googleapis.com/auth/admin.directory.group.readonly` (grupos - painel)
   - `https://www.googleapis.com/auth/admin.directory.orgunit.readonly` (unidades organizacionais - painel)
5. Configure no `.env`:

```env
GOOGLE_ADMIN_ENABLED=true
GOOGLE_SERVICE_ACCOUNT_FILE=C:\secure\google\service-account.json
GOOGLE_DELEGATED_ADMIN=admin@empresa.com.br
GOOGLE_WORKSPACE_DOMAIN=empresa.com.br
```

Regras aplicadas no fluxo de demissão:

- Se não houver email do colaborador, o Google é **pulado** e o processo continua.
- Se o email do colaborador for igual ao admin delegado, o Google é **pulado**.
- Se ocorrer erro no Google, os demais sistemas continuam normalmente.

Teste rápido de autenticação (PowerShell):

```powershell
python -c "from dotenv import load_dotenv; load_dotenv('.env'); from google.oauth2 import service_account; from googleapiclient.discovery import build; import os; f=os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE'); a=os.getenv('GOOGLE_DELEGATED_ADMIN'); scopes=['https://www.googleapis.com/auth/admin.directory.user.readonly']; creds=service_account.Credentials.from_service_account_file(f, scopes=scopes).with_subject(a); svc=build('admin','directory_v1',credentials=creds,cache_discovery=False); resp=svc.users().get(userKey=a).execute(); print('OK Google Admin:', resp.get('primaryEmail'))"
```

### 4. Integração Infomed (Oracle)

O painel acessa o banco Oracle do Infomed **direto** (sem passar pela tela do sistema), na tabela `API.API_USUARIOS`. Duas formas de configurar a conexão — ver comentários completos no `env.example`:

- **Opção A:** `INFOMED_DB_HOST` + `INFOMED_DB_PORT` + `INFOMED_DB_SERVICE` (valores reais, achados no `tnsnames.ora` ou perguntando à SYS_CONTEXT do próprio banco)
- **Opção B:** `INFOMED_DB_DSN` (o alias que o PL/SQL Developer já usa, ex: `ORA_NOVA`) + `INFOMED_TNS_ADMIN` (pasta do `tnsnames.ora`)

Se aparecer o erro `DPY-3015` (senha em formato pré-12c), instale o Oracle Instant Client e configure `INFOMED_ORACLE_CLIENT_DIR` apontando pra pasta dele — ativa o "modo thick", que entende os dois formatos de senha.

## Execução (ambiente local)

### 1. Iniciar servidor (desenvolvimento)
```bash
python server.py
```

Ou, com o servidor de produção (Waitress):
```bash
python -m waitress --host=0.0.0.0 --port=3000 server:app
```

O painel web fica disponível em `http://localhost:3000/painel`.

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

> **Dica:** se o terminal travar sozinho (só volta a responder depois de apertar Enter), é o **QuickEdit Mode** do console do Windows — qualquer clique/seleção na janela pausa a saída do programa. Desmarque em Propriedades **e** em Padrões (Defaults) da janela do CMD, e abra uma janela nova depois de mudar. Pra eliminar o problema de vez, considere rodar como **Serviço do Windows** (ex.: via NSSM), que não usa console interativo.

## Estrutura

```
├── server.py               # Servidor Flask principal (webhook + fluxo automático)
├── inativar_manual.py      # Ativação/inativação manual (contingência, ou reverter engano/voltar de férias)
├── google_admin.py         # Conexão com Google Admin SDK (compartilhada por server.py e painel/)
├── rpa_crm.py               # RPA - CRM JMJ (email)
├── rpa_saw.py                # RPA - SAW (email)
├── rpa_giu.py                # RPA - GIU Unimed (CPF)
├── rpa_ged.py                # RPA - GED Bye Bye Paper (email)
├── rpa_tasy.py               # RPA - Tasy EMR (nome completo + nome de conta)
├── rpa_infomed.py            # Ativa/inativa no Infomed via banco Oracle (email)
├── rpa_nextqs.py             # RPA - NextQS Manager (não executado - bloqueado por Cloudflare)
├── rpa_bplus.py              # RPA - B+ Reembolso (não ligado a nenhum fluxo)
├── inspecionar_pagina.py    # Ferramenta para mapear novos sites
├── painel/                   # Blueprint Flask do painel web
│   ├── __init__.py            # Rotas
│   ├── ad_gestao.py            # Busca/edição de usuários AD (horário, senha, bloqueio)
│   ├── auth_ad.py               # Login do painel via AD
│   ├── tangerino.py             # Integração com API do Tangerino (colaboradores, férias)
│   ├── google_workspace.py     # Usuários/grupos/OUs do Google Workspace
│   ├── infomed.py                # Conexão Oracle direta com o Infomed
│   ├── jobs.py                    # Job em background da ativação/inativação manual
│   ├── rpa_status_jobs.py        # Job em background da consulta de status (aba Sistemas)
│   ├── webhooks.py                # Inspeção/reprocessamento de webhooks
│   ├── exportacao.py              # Exportação de Excel
│   └── utils.py                    # Funções utilitárias (senha, CPF, etc)
├── templates/painel/         # Templates HTML do painel
├── static/painel/             # CSS/estáticos do painel
├── logs/                      # Pasta de logs (criada automaticamente)
│   ├── integracao_solides.log  # Log geral
│   └── webhooks.log            # Log de webhooks
├── data/                       # CSV de histórico de desligamentos
├── env.example                # Template de variáveis
├── requirements.txt           # Dependências Python
└── README.md                  # Este arquivo
```

## Endpoints

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/status` | GET | Status do servidor |
| `/webhook/solides` | POST | Recebe webhook de demissão |
| `/consulta-ad` | POST | Consulta usuário no AD |
| `/sistemas/status` | GET | Status dos sistemas RPA |
| `/painel/*` | GET/POST | Painel web (login, dashboard, colaboradores, AD, Google Workspace, Infomed, férias, ativação/inativação manual, webhooks, logs) — ver `painel/__init__.py` para a lista completa de rotas |

## Sistemas Integrados

| Sistema | Script/Módulo | Identificador | No fluxo automático? | No painel (manual)? |
|---------|---------------|---------------|:---:|:---:|
| Active Directory | `painel/ad_gestao.py` (painel) | CPF | ✅ | ✅ |
| Google Workspace | `google_admin.py` | Email | ✅ (opcional) | ✅ (leitura/gestão) |
| CRM JMJ | `rpa_crm.py` | Email | ✅ | ✅ |
| SAW | `rpa_saw.py` | Email | ✅ | ✅ |
| GIU Unimed | `rpa_giu.py` | CPF | ✅ | ✅ |
| GED Bye Bye Paper | `rpa_ged.py` | Email | ✅ | ✅ |
| Tasy EMR | `rpa_tasy.py` | Nome completo + nome de conta | ✅ | ✅ |
| Infomed | `rpa_infomed.py` / `painel/infomed.py` | Email corporativo | ✅ | ✅ |
| NextQS Manager | `rpa_nextqs.py` | Email | ❌ (Cloudflare Turnstile bloqueia) | ❌ |
| B+ Reembolso | `rpa_bplus.py` | Nome de conta | ❌ (nunca foi ligado) | ❌ |

Todos os sistemas marcados com ✅ nos dois fluxos suportam **ativar e desativar** (não só desativar).

## Proteção contra Duplicatas

O sistema tem **duas camadas** de proteção contra reprocessar o mesmo desligamento:

1. **Memória de curto prazo** (5 minutos) — pega retentativas rápidas do mesmo webhook.
2. **Histórico persistente** (CSV) — mesmo que o webhook chegue horas ou dias depois pro mesmo CPF + data de desligamento, o sistema reconhece que já foi processado e não reprocessa (evita rodar todos os RPAs de novo à toa).

O botão "Reprocessar" do inspetor de webhooks (painel) contorna essa proteção de propósito, pra permitir forçar um reprocessamento manual quando necessário.

## Inativação Parcial (Usuário não encontrado no AD)

Quando o usuário não é encontrado no Active Directory, o sistema:

1. Continua a inativação nos sistemas que usam **somente CPF** (ex: GIU)
2. Pula os sistemas que precisam de dados do AD (email, nome)
3. Envia email de notificação normalmente (com status "Não encontrado no AD")

## Ativação/Inativação Manual (Contingência)

Disponível tanto pela **tela do painel** (`/painel/inativacao-manual`, com toggle Ativar/Inativar) quanto por linha de comando:

```bash
# Inativar em todos os sistemas + enviar email
python inativar_manual.py --cpf 01234567890 --email joao.silva@empresa.com.br --nome "JOAO DA SILVA" --enviar-email

# Ativar (ex: colaborador voltando de férias, ou inativado por engano)
python inativar_manual.py --cpf 01234567890 --email joao.silva@empresa.com.br --nome "JOAO DA SILVA" --acao ativar

# Pular o AD (quando usuário não existe no AD)
python inativar_manual.py --cpf 01234567890 --email joao.silva@empresa.com.br --nome "JOAO DA SILVA" --pular-ad --enviar-email

# Apenas sistemas específicos
python inativar_manual.py --cpf 01234567890 --sistemas giu
python inativar_manual.py --email joao.silva@empresa.com.br --sistemas crm saw ged infomed
```

### Parâmetros disponíveis

| Parâmetro | Descrição |
|-----------|-----------|
| `--cpf` | CPF do colaborador (usado no AD e GIU) |
| `--email` | Email corporativo (usado nos demais sistemas) |
| `--nome` | Nome completo (necessário para Tasy) |
| `--sistemas` | Lista de sistemas: `ad`, `crm`, `saw`, `giu`, `ged`, `tasy`, `infomed` |
| `--acao` | `ativar` ou `desativar` (padrão: `desativar`) |
| `--pular-ad` | Não tentar mexer no Active Directory |
| `--enviar-email` | Enviar email de notificação para o TI |

> Reativação (`--acao ativar`) **não é registrada** no CSV de histórico de desligamentos, já que não é um desligamento — só desativações entram nesse histórico.

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
- `WORKPLACE_CACHE_TTL_SECONDS` / `JOB_ROLE_CACHE_TTL_SECONDS` / `EMPLOYEES_CACHE_TTL_SECONDS`: tempo de cache das consultas ao Tangerino no painel (padrão: 600s / 600s / 90s)

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

## Troubleshooting

### Erro "JavaScript heap out of memory" (GIU/GED/etc)

Os RPAs usam **Playwright**, que executa um processo **Node.js** internamente. Em alguns ambientes (principalmente Windows/VM), o Node pode estourar o heap padrão e encerrar com:

- `FATAL ERROR: ... JavaScript heap out of memory`

**Correção recomendada:** defina no `.env`:

```env
PLAYWRIGHT_MAX_OLD_SPACE_SIZE_MB=4096
```

Se precisar aplicar temporariamente no PowerShell (sem mexer no `.env`):

```powershell
$env:NODE_OPTIONS="--max-old-space-size=4096"
python server.py
```

### Erro `DPY-3015` ao conectar no Infomed

Senha do usuário do banco Oracle em formato antigo (pré-12c), que o modo "thin" do `oracledb` não lê. Instale o Oracle Instant Client e configure `INFOMED_ORACLE_CLIENT_DIR` no `.env` — ativa o "modo thick", que entende os dois formatos. Alternativa: pedir pra um DBA redefinir a senha do usuário (`ALTER USER ... IDENTIFIED BY ...`), o que regera o hash em formato novo.

### Erro `getaddrinfo failed` ao conectar no Infomed

Falha de DNS/rede — a máquina onde o painel roda não consegue resolver o hostname configurado. Confirme se está usando o nome/IP corretos (ex.: via `tnsnames.ora` ou `SYS_CONTEXT('USERENV','SERVER_HOST')` no próprio banco) e se há rota de rede até lá (`Test-NetConnection -ComputerName HOST -Port 1521` no PowerShell).

### Terminal trava, só volta ao apertar Enter

É o **QuickEdit Mode** do console do Windows (ver seção de execução em VM acima).

## Criando RPA para Novos Sites

Use o script de inspeção para mapear elementos de novos sistemas:

```bash
python inspecionar_pagina.py https://novo-sistema.com/login
```

O gravador captura cliques e digitação, gerando o código automaticamente.

---

**Desenvolvido por:** Marcos Vinicius Viana Lima
**Versão:** 3.0
