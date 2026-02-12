# Integração Solides - Active Directory + Sistemas

Sistema automatizado que recebe webhooks do Solides quando um colaborador é demitido e executa:

- ✅ Desativa o usuário no **Active Directory**
- ✅ Desativa no **CRM JMJ**
- ✅ Desativa no **SAW**
- ✅ Desativa no **GIU Unimed**
- ✅ Bloqueia no **GED Bye Bye Paper**
- ✅ Desativa no **B+ Reembolso**
- ✅ Desativa no **Tasy EMR**
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
Solides → Webhook → ngrok → Servidor Local → AD + CRM + SAW + GIU + GED + NextQS + B+ + Email

> Observação: **NextQS não é executado** no momento.
```

## Instalação

```bash
# Criar ambiente virtual
python -m venv venv
venv\Scripts\activate

# Instalar dependências
pip install -r requirements.txt

# Instalar Playwright (navegador para RPA)
playwright install chromium
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

## Execução

### 1. Iniciar servidor
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

**Características:**
- Rotação automática: 5MB por arquivo, mantém 10 backups
- Formato: `2026-02-04 14:30:25 | INFO | [WEBHOOK] Mensagem...`

**Consultar logs (PowerShell):**
```powershell
# Últimas 50 linhas
Get-Content logs\integracao_solides.log -Tail 50

# Buscar por CPF
Select-String -Path logs\*.log -Pattern "12345678900"

# Buscar erros
Select-String -Path logs\integracao_solides.log -Pattern "ERROR"
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

## Documentação Completa

Para procedimentos detalhados, consulte o **POP (Procedimento Operacional Padrão)**: `POP_INTEGRACAO_SOLIDES.md`
