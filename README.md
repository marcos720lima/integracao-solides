# Integração Solides - Active Directory + Sistemas

Este projeto surgiu a partir de um desafio proposto pela coordenação, com o objetivo de automatizar o processo de inativação de acessos de colaboradores desligados da empresa. A solução desenvolvida elimina a necessidade de acionamento manual do setor de TI pelo Departamento Pessoal a cada demissão, reduzindo riscos de segurança, tempo operacional e dependência de processos manuais.

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
Solides → Webhook → ngrok → Servidor Local → AD + CRM + SAW + GIU + GED + NextQS + Email
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

# NextQS Manager
NEXTQS_URL=https://manager.nextqs.com
NEXTQS_USERNAME=seu-email@empresa.com
NEXTQS_PASSWORD=sua-senha
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
├── rpa_crm.py             # RPA - CRM JMJ (email)
├── rpa_saw.py             # RPA - SAW (email)
├── rpa_giu.py             # RPA - GIU Unimed (CPF)
├── rpa_ged.py             # RPA - GED Bye Bye Paper (email)
├── rpa_nextqs.py          # RPA - NextQS Manager (email)
├── env.example            # Template de variáveis
├── requirements.txt       # Dependências Python
└── README.md              # Documentação
```

## 🔌 Endpoints

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
| NextQS Manager | `rpa_nextqs.py` | Email | Desativa usuário |

## 📧 Email de Notificação

```
NOTIFICAÇÃO: Colaborador Demitido - Nome

Informações do Colaborador
├── Nome, CPF, Email
├── Setor, Cargo, Matrícula
└── Data Demissão

Inativações Realizadas
├── AD (Active Directory): ✅ Desativado
├── CRM JMJ:               ✅ Desativado
├── SAW:                   ✅ Desativado
├── GIU Unimed:            ✅ Desativado
├── GED (Bye Bye Paper):   ✅ Bloqueado
└── NextQS Manager:        ✅ Desativado

Ações Recomendadas
├── Revogar acessos VPN
├── Verificar outros sistemas
└── Recolher equipamentos
```

## Proteção contra Duplicatas

O sistema bloqueia o mesmo CPF por **5 minutos** para evitar processamento duplicado.

---

**Desenvolvido por:** Marcos Vinicius Viana Lima  
**Versão:** 2.2
