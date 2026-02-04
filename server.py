"""
Servidor de Integração Solides - Active Directory + Sistemas

Este servidor recebe webhooks do Solides quando um colaborador é demitido
e automatiza a desativação em todos os sistemas corporativos.

Autor: Marcos Vinicius Viana Lima
Versão: 2.4
"""

import json
import logging
import os
import re
import smtplib
import subprocess
import threading
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from ldap3 import ALL, Connection, MODIFY_REPLACE, Server

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AD_URL = os.getenv('AD_URL')
AD_USER = os.getenv('AD_USER')
AD_PASS = os.getenv('AD_PASS')
BASE_DN = os.getenv('BASE_DN')

EMAIL_CONFIG = {
    'smtp_server': os.getenv('EMAIL_SMTP_SERVER', 'smtp.gmail.com'),
    'smtp_port': int(os.getenv('EMAIL_SMTP_PORT', 587)),
    'username': os.getenv('EMAIL_USERNAME'),
    'password': os.getenv('EMAIL_PASSWORD')
}

WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')
TI_EMAILS = os.getenv('TI_EMAILS', '').split(',')

cpfs_processados = {}
TEMPO_BLOQUEIO_DUPLICATA = 300

STATUS_NAO_EXECUTADO = "Não executado"
STATUS_DESATIVADO = "Desativado"
STATUS_BLOQUEADO = "Bloqueado"
STATUS_JA_INATIVO = "Já estava inativo"
STATUS_JA_BLOQUEADO = "Já estava bloqueado"
STATUS_SEM_ACESSO = "Não possui acesso"

SISTEMAS_CONFIG = {
    'crm_jmj': {
        'ativo': True,
        'script': 'rpa_crm.py',
        'timeout': 300,
        'nome': 'CRM JMJ',
        'requer_ad': True  # Precisa do email do AD
    },
    'saw': {
        'ativo': True,
        'script': 'rpa_saw.py',
        'timeout': 300,
        'nome': 'SAW',
        'requer_ad': True  # Precisa do email do AD
    },
    'giu': {
        'ativo': True,
        'script': 'rpa_giu.py',
        'timeout': 300,
        'nome': 'GIU Unimed',
        'requer_ad': False  # Usa somente CPF
    },
    'ged': {
        'ativo': True,
        'script': 'rpa_ged.py',
        'timeout': 300,
        'nome': 'GED Bye Bye Paper',
        'requer_ad': True  # Precisa do email do AD
    },
    'sso_email': {
        'ativo': False,
        'script': 'rpa_sso_email.py',
        'timeout': 300,
        'nome': 'SSO Email Unimed',
        'requer_ad': True  # Precisa do email do AD
    },
    'nextqs': {
        'ativo': False,
        'script': 'rpa_nextqs.py',
        'timeout': 300,
        'nome': 'NextQS Manager',
        'requer_ad': True  # Precisa do email do AD
    },
    'bplus': {
        'ativo': True,
        'script': 'rpa_bplus.py',
        'timeout': 300,
        'nome': 'B+ Reembolso',
        'requer_ad': True  # Precisa do email do AD
    },
    'tasy': {
        'ativo': True,
        'script': 'rpa_tasy.py',
        'timeout': 300,
        'nome': 'Tasy EMR',
        'requer_ad': True  # Precisa do nome/email do AD
    }
}

app = Flask(__name__)

CORS(app, resources={
    r"/*": {
        "origins": ["*"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})


def limpar_cpf(cpf):
    """Remove formatação do CPF, deixando apenas números."""
    if not cpf:
        return None
    return re.sub(r'[.\-\s]', '', cpf)


def formatar_cpf(cpf):
    """Formata CPF para exibição (XXX.XXX.XXX-XX)."""
    if not cpf:
        return 'N/A'
    cpf_limpo = limpar_cpf(cpf)
    if not cpf_limpo or len(cpf_limpo) != 11:
        return cpf
    return f"{cpf_limpo[:3]}.{cpf_limpo[3:6]}.{cpf_limpo[6:9]}-{cpf_limpo[9:]}"


def obter_status_formatado(sistema, usar_bloqueado=False):
    """Converte status do sistema para texto legível."""
    status = sistema.get('status')
    
    if status == 'sucesso':
        return STATUS_BLOQUEADO if usar_bloqueado else STATUS_DESATIVADO
    elif status == 'ja_inativo':
        return STATUS_JA_BLOQUEADO if usar_bloqueado else STATUS_JA_INATIVO
    elif status == 'nao_encontrado':
        return STATUS_SEM_ACESSO
    elif status == 'erro':
        erro = sistema.get('erro', 'Erro desconhecido')[:40]
        return f"Erro: {erro}"
    
    return STATUS_NAO_EXECUTADO


def executar_sistema_rpa(sistema_id, email_usuario, cpf_usuario=None, nome_completo=None):
    """Executa o script RPA de um sistema específico."""
    config = SISTEMAS_CONFIG.get(sistema_id)
    
    if not config or not config['ativo']:
        return {
            'status': 'skipped',
            'sistema': config['nome'] if config else sistema_id,
            'motivo': f'Sistema {sistema_id} não configurado ou inativo'
        }
    
    script = config['script']
    timeout = config['timeout']
    nome = config['nome']
    
    if sistema_id == 'giu' and cpf_usuario:
        parametro = cpf_usuario
        logger.info(f"[RPA] Executando {nome} para CPF: {cpf_usuario}")
    elif sistema_id == 'tasy' and nome_completo:
        nome_conta = email_usuario.split('@')[0] if email_usuario else ''
        parametro = f'"{nome_completo}" {nome_conta}'
        logger.info(f"[RPA] Executando {nome} para: {nome_completo} ({nome_conta})")
    else:
        parametro = email_usuario
        logger.info(f"[RPA] Executando {nome} para email: {email_usuario}")
    
    if not os.path.exists(script):
        logger.error(f"[ERRO] Script {script} não encontrado")
        return {
            'status': 'erro',
            'sistema': nome,
            'erro': f'Script {script} não encontrado'
        }
    
    try:
        cmd = f'python {script} "{parametro}"'
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd(),
            shell=True
        )
        
        return _interpretar_resultado_rpa(process, nome)
        
    except subprocess.TimeoutExpired:
        logger.error(f"[ERRO] Timeout no {nome}")
        return {
            'status': 'erro',
            'sistema': nome,
            'erro': f'Timeout de {timeout}s excedido'
        }
    except Exception as e:
        logger.error(f"[ERRO] Exceção no {sistema_id}: {str(e)}")
        return {
            'status': 'erro',
            'sistema': sistema_id,
            'erro': str(e)
        }


def _interpretar_resultado_rpa(process, nome):
    """Interpreta o código de retorno do RPA."""
    codigo = process.returncode
    
    if codigo == 0:
        logger.info(f"[OK] {nome}: Desativado com sucesso!")
        return {'status': 'sucesso', 'sistema': nome, 'log': process.stdout}
    
    elif codigo == 2:
        logger.info(f"[AVISO] {nome}: Já estava inativo/bloqueado")
        return {'status': 'ja_inativo', 'sistema': nome, 'log': process.stdout}
    
    elif codigo == 3:
        logger.info(f"[INFO] {nome}: Usuário não possui acesso")
        return {'status': 'nao_encontrado', 'sistema': nome, 'log': process.stdout}
    
    else:
        logger.error(f"[ERRO] Erro no {nome}: {process.stderr}")
        return {
            'status': 'erro',
            'sistema': nome,
            'erro': process.stderr,
            'log': process.stdout
        }


def _criar_conexao_ad():
    """Cria e retorna uma conexão com o Active Directory."""
    server = Server(AD_URL, get_info=ALL, use_ssl=True)
    return Connection(
        server,
        user=AD_USER,
        password=AD_PASS,
        auto_bind=True,
        authentication='SIMPLE'
    )


def desativar_usuario_por_cpf(cpf):
    """Desativa um usuário no AD pelo CPF (employeeID)."""
    logger.info(f"[PROC] Iniciando desativação do usuário com CPF: {cpf}")
    
    conn = _criar_conexao_ad()
    logger.info("Conectado no AD para desativação")
    
    try:
        search_filter = f"(&(objectClass=user)(employeeID={cpf}))"
        attributes = ['userAccountControl', 'sAMAccountName', 'employeeID', 'cn', 'displayName']
        
        conn.search(BASE_DN, search_filter, attributes=attributes)
        
        if not conn.entries:
            raise ValueError(f"Usuário com CPF/EmployeeID {cpf} não encontrado no AD")
        
        usuario = conn.entries[0]
        nome_usuario = usuario.displayName.value if usuario.displayName else usuario.cn.value
        
        logger.info("👤 Usuário encontrado para desativação:")
        logger.info(f"   - Nome: {nome_usuario}")
        logger.info(f"   - Login: {usuario.sAMAccountName.value}")
        logger.info(f"   - EmployeeID: {usuario.employeeID.value}")
        
        user_dn = str(usuario.entry_dn)
        modificacao = {'userAccountControl': [(MODIFY_REPLACE, [514])]}
        
        if not conn.modify(user_dn, modificacao):
            raise RuntimeError(f"Erro ao desativar usuário: {conn.result}")
        
        logger.info(f"[OK] Usuário {usuario.sAMAccountName.value} (CPF: {cpf}) desativado com sucesso no AD")
        
        return {
            'cpf': cpf,
            'login': usuario.sAMAccountName.value,
            'nome': nome_usuario,
            'employeeID': usuario.employeeID.value,
            'dn': user_dn,
            'status': 'desativado'
        }
        
    finally:
        conn.unbind()


def consultar_email_por_cpf(cpf):
    """Consulta o email de um usuário no AD pelo CPF."""
    logger.info(f"[EMAIL] Consultando email no AD para CPF: {cpf}")
    
    conn = _criar_conexao_ad()
    
    try:
        search_filter = f"(&(objectClass=user)(employeeID={cpf}))"
        attributes = ['mail', 'userPrincipalName', 'sAMAccountName']
        
        conn.search(BASE_DN, search_filter, attributes=attributes)
        
        if not conn.entries:
            raise ValueError(f"Usuário com CPF {cpf} não encontrado")
        
        usuario = conn.entries[0]
        
        if usuario.mail and usuario.mail.value:
            email = str(usuario.mail.value)
        elif usuario.userPrincipalName and usuario.userPrincipalName.value:
            email = str(usuario.userPrincipalName.value)
        else:
            email = f"{usuario.sAMAccountName.value}@unimedoestedopara.coop.br"
        
        logger.info(f"[EMAIL] Email encontrado: {email}")
        return email
        
    finally:
        conn.unbind()


def enviar_email_notificacao(dados_colaborador, resultado_ad, resultado_sistemas=None):
    """Envia email de notificação sobre a desativação do colaborador."""
    logger.info("[EMAIL] Iniciando envio de notificação...")
    
    server = smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port'])
    server.starttls()
    server.login(EMAIL_CONFIG['username'], EMAIL_CONFIG['password'])
    
    logger.info("[OK] [EMAIL] Conexão SMTP estabelecida")
    
    cpf_correto = resultado_ad.get('cpf') or dados_colaborador.get('documentos', {}).get('cpf', 'N/A')
    cpf_formatado = formatar_cpf(cpf_correto)
    
    status_sistemas = _obter_status_sistemas(resultado_ad, resultado_sistemas)
    
    nome_colaborador = dados_colaborador.get('nome', 'N/A')
    setor = dados_colaborador.get('departamento', {}).get('nome', 'N/A')
    cargo = dados_colaborador.get('cargo', {}).get('nome', 'N/A')
    
    html_content = _gerar_html_email(
        nome_colaborador, cpf_formatado, dados_colaborador,
        setor, cargo, status_sistemas, resultado_ad
    )
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"NOTIFICAÇÃO: Colaborador Demitido - {nome_colaborador}"
    msg['From'] = EMAIL_CONFIG['username']
    msg['To'] = ', '.join(TI_EMAILS)
    
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    server.send_message(msg)
    server.quit()
    
    logger.info("[OK] [EMAIL] Email enviado com sucesso!")
    logger.info(f"[EMAIL] Destinatários: {', '.join(TI_EMAILS)}")
    
    return {'status': 'success', 'recipients': TI_EMAILS}


def _obter_status_sistemas(resultado_ad, resultado_sistemas):
    """Extrai o status de cada sistema do resultado."""
    status = {
        'ad': STATUS_DESATIVADO if resultado_ad.get('status') == 'desativado' else "Erro ao Desativar",
        'jmj': STATUS_NAO_EXECUTADO,
        'saw': STATUS_NAO_EXECUTADO,
        'giu': STATUS_NAO_EXECUTADO,
        'ged': STATUS_NAO_EXECUTADO,
        'nextqs': STATUS_NAO_EXECUTADO,
        'bplus': STATUS_NAO_EXECUTADO,
        'tasy': STATUS_NAO_EXECUTADO
    }
    
    if not resultado_sistemas or not resultado_sistemas.get('detalhes'):
        return status
    
    for sistema in resultado_sistemas.get('detalhes', []):
        nome = sistema.get('sistema', '').upper()
        
        if 'JMJ' in nome or 'CRM' in nome:
            status['jmj'] = obter_status_formatado(sistema)
        elif 'SAW' in nome:
            status['saw'] = obter_status_formatado(sistema)
        elif 'GIU' in nome:
            status['giu'] = obter_status_formatado(sistema)
        elif 'GED' in nome or 'BYE' in nome:
            status['ged'] = obter_status_formatado(sistema, usar_bloqueado=True)
        elif 'NEXTQS' in nome:
            status['nextqs'] = obter_status_formatado(sistema)
        elif 'BPLUS' in nome or 'B+' in nome or 'REEMBOLSO' in nome:
            status['bplus'] = obter_status_formatado(sistema)
        elif 'TASY' in nome:
            status['tasy'] = obter_status_formatado(sistema)
    
    return status


def _gerar_html_email(nome, cpf, dados, setor, cargo, status, resultado_ad):
    """Gera o HTML do email de notificação."""
    return f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            h2 {{ color: #c0392b; border-bottom: 2px solid #c0392b; padding-bottom: 10px; }}
            h3 {{ color: #2c3e50; margin-top: 25px; }}
            .info-box {{ background-color: #f8f9fa; padding: 15px; border-radius: 8px; margin: 10px 0; }}
            .status-box {{ background-color: #fff3cd; padding: 15px; border-radius: 8px; margin: 10px 0; border-left: 4px solid #ffc107; }}
            table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
            td {{ padding: 8px 12px; border-bottom: 1px solid #ddd; }}
            td:first-child {{ font-weight: bold; width: 40%; background-color: #f8f9fa; }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>NOTIFICAÇÃO: Colaborador Demitido - {nome}</h2>
            
            <h3>Informações do Colaborador</h3>
            <div class="info-box">
                <table>
                    <tr><td>Nome:</td><td>{nome}</td></tr>
                    <tr><td>CPF:</td><td>{cpf}</td></tr>
                    <tr><td>Email:</td><td>{dados.get('email', 'N/A')}</td></tr>
                    <tr><td>Setor:</td><td>{setor}</td></tr>
                    <tr><td>Cargo:</td><td>{cargo}</td></tr>
                    <tr><td>Matrícula:</td><td>{dados.get('matricula', 'N/A')}</td></tr>
                    <tr><td>Data Demissão:</td><td>{dados.get('data_demissao', 'N/A')}</td></tr>
                </table>
            </div>
            
            <h3>Inativações Realizadas</h3>
            <div class="status-box">
                <table>
                    <tr><td>AD (Active Directory):</td><td>{status['ad']}</td></tr>
                    <tr><td>CRM JMJ:</td><td>{status['jmj']}</td></tr>
                    <tr><td>SAW:</td><td>{status['saw']}</td></tr>
                    <tr><td>GIU Unimed:</td><td>{status['giu']}</td></tr>
                    <tr><td>GED (Bye Bye Paper):</td><td>{status['ged']}</td></tr>
                    <tr><td>B+ Reembolso:</td><td>{status['bplus']}</td></tr>
                    <tr><td>Tasy EMR:</td><td>{status['tasy']}</td></tr>
                </table>
            </div>
            
            <h3>Detalhes do Active Directory</h3>
            <div class="info-box">
                <table>
                    <tr><td>Login AD:</td><td>{resultado_ad.get('login', 'N/A')}</td></tr>
                    <tr><td>Nome AD:</td><td>{resultado_ad.get('nome', 'N/A')}</td></tr>
                    <tr><td>EmployeeID:</td><td>{resultado_ad.get('employeeID', resultado_ad.get('cpf', 'N/A'))}</td></tr>
                    <tr><td>Data/Hora:</td><td>{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</td></tr>
                </table>
            </div>
            
            <h3>Ações Recomendadas</h3>
            <ul>
                <li>Verificar acesso a demais sistemas não inseridos no fluxo</li>
                <li>Confirmar desativação do email corporativo</li>
            </ul>
            
            <div class="footer">
                <p><em>Esta é uma notificação automática do sistema de integração Solides + Active Directory.</em></p>
                <p><em>Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}</em></p>
            </div>
        </div>
    </body>
    </html>
    """


def enviar_email_notificacao_parcial(dados_colaborador, cpf, resultado_sistemas=None):
    """Envia email de notificação quando usuário NÃO foi encontrado no AD."""
    logger.info("[EMAIL] Iniciando envio de notificação PARCIAL (usuário não encontrado no AD)...")
    
    server = smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port'])
    server.starttls()
    server.login(EMAIL_CONFIG['username'], EMAIL_CONFIG['password'])
    
    logger.info("[OK] [EMAIL] Conexão SMTP estabelecida")
    
    cpf_bruto = dados_colaborador.get('documentos', {}).get('cpf', cpf)
    cpf_formatado = formatar_cpf(cpf_bruto)
    
    nome_colaborador = dados_colaborador.get('nome', 'N/A')
    setor = dados_colaborador.get('departamento', {}).get('nome', 'N/A')
    cargo = dados_colaborador.get('cargo', {}).get('nome', 'N/A')
    
    html_content = _gerar_html_email_parcial(
        nome_colaborador, cpf_formatado, dados_colaborador,
        setor, cargo, resultado_sistemas
    )
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"⚠️ ATENÇÃO: Inativação Parcial - {nome_colaborador} (Usuário não encontrado no AD)"
    msg['From'] = EMAIL_CONFIG['username']
    msg['To'] = ', '.join(TI_EMAILS)
    
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    server.send_message(msg)
    server.quit()
    
    logger.info("[OK] [EMAIL] Email de notificação parcial enviado com sucesso!")
    logger.info(f"[EMAIL] Destinatários: {', '.join(TI_EMAILS)}")
    
    return {'status': 'success', 'recipients': TI_EMAILS}


def _gerar_html_email_parcial(nome, cpf, dados, setor, cargo, resultado_sistemas):
    """Gera o HTML do email de notificação parcial (usuário não encontrado no AD)."""
    
    # Monta lista de sistemas executados
    sistemas_executados_html = ""
    if resultado_sistemas and resultado_sistemas.get('detalhes'):
        for sistema in resultado_sistemas['detalhes']:
            status = obter_status_formatado(sistema)
            sistemas_executados_html += f"<tr><td>{sistema.get('sistema', 'N/A')}:</td><td>{status}</td></tr>"
    else:
        sistemas_executados_html = "<tr><td colspan='2'>Nenhum sistema executado</td></tr>"
    
    # Monta lista de sistemas NÃO executados (pulados)
    sistemas_pulados_html = ""
    if resultado_sistemas and resultado_sistemas.get('sistemas_pulados'):
        for sistema in resultado_sistemas['sistemas_pulados']:
            sistemas_pulados_html += f"<tr><td>{sistema.get('sistema', 'N/A')}:</td><td>Não executado - Requer AD</td></tr>"
    
    # Lista de sistemas que precisam de inativação manual
    sistemas_manuais = [
        'Active Directory (AD)',
        'CRM JMJ',
        'SAW',
        'GED (Bye Bye Paper)',
        'B+ Reembolso',
        'Tasy EMR',
        'Email Corporativo'
    ]
    sistemas_manuais_html = "".join([f"<li>{s}</li>" for s in sistemas_manuais])
    
    return f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            h2 {{ color: #e74c3c; border-bottom: 2px solid #e74c3c; padding-bottom: 10px; }}
            h3 {{ color: #2c3e50; margin-top: 25px; }}
            .info-box {{ background-color: #f8f9fa; padding: 15px; border-radius: 8px; margin: 10px 0; }}
            .warning-box {{ background-color: #fff3cd; padding: 15px; border-radius: 8px; margin: 10px 0; border-left: 4px solid #ffc107; }}
            .error-box {{ background-color: #f8d7da; padding: 15px; border-radius: 8px; margin: 10px 0; border-left: 4px solid #dc3545; }}
            .success-box {{ background-color: #d4edda; padding: 15px; border-radius: 8px; margin: 10px 0; border-left: 4px solid #28a745; }}
            table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
            td {{ padding: 8px 12px; border-bottom: 1px solid #ddd; }}
            td:first-child {{ font-weight: bold; width: 40%; background-color: #f8f9fa; }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }}
            ul {{ margin: 10px 0; padding-left: 20px; }}
            li {{ margin: 5px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>⚠️ ATENÇÃO: Inativação Parcial Realizada</h2>
            
            <div class="error-box">
                <strong>🚨 USUÁRIO NÃO ENCONTRADO NO ACTIVE DIRECTORY</strong>
                <p>O colaborador com CPF <strong>{cpf}</strong> não foi localizado no Active Directory. 
                Apenas os sistemas que utilizam <strong>somente o CPF</strong> foram processados.</p>
                <p><strong>É necessária intervenção manual para inativar os demais sistemas.</strong></p>
            </div>
            
            <h3>Informações do Colaborador</h3>
            <div class="info-box">
                <table>
                    <tr><td>Nome:</td><td>{nome}</td></tr>
                    <tr><td>CPF:</td><td>{cpf}</td></tr>
                    <tr><td>Email (Solides):</td><td>{dados.get('email', 'N/A')}</td></tr>
                    <tr><td>Setor:</td><td>{setor}</td></tr>
                    <tr><td>Cargo:</td><td>{cargo}</td></tr>
                    <tr><td>Matrícula:</td><td>{dados.get('matricula', 'N/A')}</td></tr>
                    <tr><td>Data Demissão:</td><td>{dados.get('data_demissao', 'N/A')}</td></tr>
                </table>
            </div>
            
            <h3>✅ Sistemas Processados (Somente CPF)</h3>
            <div class="success-box">
                <table>
                    {sistemas_executados_html}
                </table>
            </div>
            
            <h3>❌ Sistemas NÃO Processados (Requerem AD)</h3>
            <div class="warning-box">
                <table>
                    {sistemas_pulados_html}
                </table>
            </div>
            
            <h3>📋 Ações Manuais Necessárias</h3>
            <div class="error-box">
                <p><strong>Gentileza verificar os logs e prosseguir com a inativação MANUAL dos seguintes sistemas:</strong></p>
                <ul>
                    {sistemas_manuais_html}
                </ul>
                <p><em>Verifique também se o CPF/EmployeeID do colaborador está cadastrado corretamente no Active Directory.</em></p>
            </div>
            
            <h3>🔍 Possíveis Causas</h3>
            <div class="info-box">
                <ul>
                    <li>CPF não cadastrado no campo EmployeeID do Active Directory</li>
                    <li>Colaborador terceirizado sem conta no AD</li>
                    <li>Colaborador novo que ainda não teve conta criada no AD</li>
                    <li>CPF cadastrado com formatação diferente no AD</li>
                </ul>
            </div>
            
            <div class="footer">
                <p><em>Esta é uma notificação automática do sistema de integração Solides + Active Directory.</em></p>
                <p><em>Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}</em></p>
            </div>
        </div>
    </body>
    </html>
    """


def processar_demissao_async(dados, cpf):
    """Processa a demissão em background (thread separada)."""
    try:
        logger.info("🏢 PASSO 1: Desativando usuário no Active Directory...")
        resultado_ad = None
        usuario_encontrado_ad = True
        
        try:
            resultado_ad = desativar_usuario_por_cpf(cpf)
            logger.info(f"[OK] Usuário desativado no AD: {resultado_ad}")
        except ValueError as ad_error:
            # Usuário não encontrado no AD
            if "não encontrado no AD" in str(ad_error):
                usuario_encontrado_ad = False
                logger.warning("[AVISO] Usuário não encontrado no AD. Prosseguindo com sistemas que usam somente CPF...")
                resultado_ad = {
                    'cpf': cpf,
                    'status': 'nao_encontrado',
                    'erro': str(ad_error)
                }
            else:
                raise ad_error
        
        nome_completo = dados.get('nome', '')
        logger.info(f"[NOME] Nome completo: {nome_completo}")
        
        if usuario_encontrado_ad:
            # Fluxo normal: usuário encontrado no AD
            email_usuario = _obter_email_usuario(resultado_ad, dados, cpf)
            logger.info(f"[EMAIL] Email capturado: {email_usuario}")
            
            logger.info("[RPA] PASSO 2: Desativando usuário nos sistemas externos...")
            resultado_sistemas = _executar_rpas(email_usuario, cpf, nome_completo)
            
            logger.info("[EMAIL] PASSO 3: Enviando email de notificação...")
            try:
                enviar_email_notificacao(dados, resultado_ad, resultado_sistemas)
                logger.info("[OK] Email de notificação enviado com sucesso!")
            except Exception as email_error:
                logger.error(f"[ERRO] ERRO ao enviar email: {str(email_error)}")
        else:
            # Fluxo parcial: usuário NÃO encontrado no AD
            # Executa apenas sistemas que não requerem AD (usam somente CPF)
            logger.info("[RPA] PASSO 2: Executando APENAS sistemas que usam somente CPF...")
            resultado_sistemas = _executar_rpas_somente_cpf(cpf, nome_completo)
            
            logger.info("[EMAIL] PASSO 3: Enviando email de notificação PARCIAL...")
            try:
                enviar_email_notificacao_parcial(dados, cpf, resultado_sistemas)
                logger.info("[OK] Email de notificação parcial enviado com sucesso!")
            except Exception as email_error:
                logger.error(f"[ERRO] ERRO ao enviar email parcial: {str(email_error)}")
        
        logger.info(f"[OK] Processamento completo para CPF: {cpf}")
        
    except Exception as e:
        logger.error(f"[ERRO] Erro no processamento async: {str(e)}")
    finally:
        if cpf in cpfs_processados:
            cpfs_processados[cpf]['processando'] = False


def _obter_email_usuario(resultado_ad, dados, cpf):
    """Obtém o email do usuário de várias fontes possíveis."""
    email = resultado_ad.get('mail') or resultado_ad.get('email')
    
    if not email:
        try:
            email = consultar_email_por_cpf(cpf)
        except Exception:
            email = dados.get('email')
    
    return email


def _executar_rpas(email_usuario, cpf, nome_completo=None):
    """Executa todos os RPAs ativos e retorna o resultado consolidado."""
    resultado = {
        'total_sistemas': 0,
        'sucessos': 0,
        'erros': 0,
        'detalhes': [],
        'status_geral': 'sucesso'
    }
    
    for sistema_id, config in SISTEMAS_CONFIG.items():
        if not config['ativo']:
            continue
            
        resultado['total_sistemas'] += 1
        logger.info(f"[PROC] Processando {config['nome']}...")
        
        resultado_rpa = executar_sistema_rpa(sistema_id, email_usuario, cpf, nome_completo)
        resultado['detalhes'].append(resultado_rpa)
        
        if resultado_rpa['status'] == 'sucesso':
            resultado['sucessos'] += 1
        elif resultado_rpa['status'] == 'erro':
            resultado['erros'] += 1
    
    if resultado['erros'] > 0 and resultado['sucessos'] > 0:
        resultado['status_geral'] = 'parcial'
    elif resultado['erros'] > 0 and resultado['sucessos'] == 0:
        resultado['status_geral'] = 'erro'
    
    return resultado


def _executar_rpas_somente_cpf(cpf, nome_completo=None):
    """Executa apenas os RPAs que não requerem AD (usam somente CPF)."""
    resultado = {
        'total_sistemas': 0,
        'sucessos': 0,
        'erros': 0,
        'skipped': 0,
        'detalhes': [],
        'sistemas_pulados': [],
        'status_geral': 'parcial'  # Sempre parcial pois não processou todos
    }
    
    for sistema_id, config in SISTEMAS_CONFIG.items():
        if not config['ativo']:
            continue
        
        # Verifica se o sistema requer AD
        if config.get('requer_ad', True):
            # Sistema requer AD, pular e registrar
            resultado['skipped'] += 1
            resultado['sistemas_pulados'].append({
                'sistema': config['nome'],
                'status': 'skipped',
                'motivo': 'Requer dados do Active Directory'
            })
            logger.info(f"[SKIP] {config['nome']} requer AD - pulando...")
            continue
        
        # Sistema não requer AD, pode executar com CPF
        resultado['total_sistemas'] += 1
        logger.info(f"[PROC] Processando {config['nome']} (somente CPF)...")
        
        resultado_rpa = executar_sistema_rpa(sistema_id, None, cpf, nome_completo)
        resultado['detalhes'].append(resultado_rpa)
        
        if resultado_rpa['status'] == 'sucesso':
            resultado['sucessos'] += 1
        elif resultado_rpa['status'] == 'erro':
            resultado['erros'] += 1
    
    return resultado


@app.route('/status', methods=['GET'])
def status():
    """Retorna o status do servidor."""
    return jsonify({
        'status': 'online',
        'servico': 'Integração Solides - AD + Sistemas',
        'versao': '2.4',
        'timestamp': datetime.now().isoformat(),
        'endpoints': {
            '/webhook/solides': 'POST - Webhook principal',
            '/consulta-ad': 'POST - Consultar usuário no AD',
            '/sistemas/status': 'GET - Status dos sistemas RPA',
            '/status': 'GET - Status do serviço'
        }
    })


@app.route('/sistemas/status', methods=['GET'])
def status_sistemas():
    """Retorna o status de todos os sistemas configurados."""
    sistemas_info = [
        {
            'id': sid,
            'nome': cfg['nome'],
            'script': cfg['script'],
            'ativo': cfg['ativo']
        }
        for sid, cfg in SISTEMAS_CONFIG.items()
    ]
    
    return jsonify({
        'status': 'online',
        'total_sistemas': len(sistemas_info),
        'ativos': sum(1 for s in sistemas_info if s['ativo']),
        'sistemas': sistemas_info
    })


@app.route('/consulta-ad', methods=['POST'])
def consulta_ad():
    """Consulta informações de um usuário no Active Directory."""
    try:
        data = request.get_json()
        login = data.get('login')
        
        logger.info(f"🚀 Iniciando consulta AD para login: {login}")
        
        if not login:
            return jsonify({'error': 'Informe o login (sAMAccountName)'}), 400
        
        conn = _criar_conexao_ad()
        logger.info("[OK] Conectado com sucesso no AD")
        
        try:
            search_filter = f"(&(objectClass=user)(sAMAccountName={login}))"
            attributes = [
                'cn', 'displayName', 'givenName', 'sn', 'sAMAccountName',
                'mail', 'employeeID', 'employeeNumber', 'department',
                'title', 'telephoneNumber', 'memberOf'
            ]
            
            conn.search(BASE_DN, search_filter, attributes=attributes)
            
            if not conn.entries:
                return jsonify({
                    'error': 'Usuário não encontrado',
                    'login_buscado': login,
                    'base_dn': BASE_DN
                }), 404
            
            usuario = conn.entries[0]
            logger.info("[OK] Usuário encontrado!")
            
            return jsonify({
                'success': True,
                'informacoes_principais': {
                    'nome_completo': str(usuario.displayName.value) if usuario.displayName else str(usuario.cn.value),
                    'email': str(usuario.mail.value) if usuario.mail else None,
                    'employee_id': _obter_employee_id(usuario),
                    'login': str(usuario.sAMAccountName.value),
                    'primeiro_nome': str(usuario.givenName.value) if usuario.givenName else None,
                    'sobrenome': str(usuario.sn.value) if usuario.sn else None,
                    'departamento': str(usuario.department.value) if usuario.department else None,
                    'cargo': str(usuario.title.value) if usuario.title else None,
                    'telefone': str(usuario.telephoneNumber.value) if usuario.telephoneNumber else None,
                    'dn': str(usuario.entry_dn)
                },
                'total_encontrados': len(conn.entries)
            })
            
        finally:
            conn.unbind()
        
    except Exception as e:
        logger.error(f"[ERRO] Erro na consulta AD: {str(e)}")
        return jsonify({'error': str(e)}), 500


def _obter_employee_id(usuario):
    """Obtém o employeeID ou employeeNumber do usuário."""
    if usuario.employeeID:
        return str(usuario.employeeID.value)
    if usuario.employeeNumber:
        return str(usuario.employeeNumber.value)
    return None


@app.route('/webhook/solides', methods=['POST'])
def webhook_solides():
    """Recebe e processa webhooks de demissão do Solides."""
    try:
        logger.info("[WEBHOOK] Webhook recebido do Solides")
        
        secret_recebido = request.headers.get('X-Webhook-Secret')
        if WEBHOOK_SECRET and secret_recebido != WEBHOOK_SECRET:
            logger.warning("[AVISO] Webhook rejeitado - Secret inválido")
            return jsonify({'status': 'erro', 'motivo': 'Secret inválido'}), 401
        
        data = request.get_json()
        logger.info(f"Body: {json.dumps(data, indent=2)}")
        
        acao = data.get('acao')
        dados = data.get('dados', {})
        
        if acao != 'demissao_colaborador':
            logger.info(f"Ação '{acao}' ignorada")
            return jsonify({'status': 'ignorado', 'acao_recebida': acao})
        
        cpf_bruto = dados.get('documentos', {}).get('cpf')
        if not cpf_bruto:
            return jsonify({'status': 'erro', 'motivo': 'CPF não encontrado'}), 400
        
        cpf = limpar_cpf(cpf_bruto)
        if not cpf or len(cpf) != 11:
            return jsonify({'status': 'erro', 'motivo': 'CPF inválido'}), 400
        
        if _cpf_ja_processado(cpf):
            return jsonify({
                'status': 'ignorado',
                'motivo': 'CPF já processado recentemente',
                'cpf': cpf
            })
        
        cpfs_processados[cpf] = {'timestamp': datetime.now(), 'processando': True}
        
        logger.info(f"🚨 DEMISSÃO DETECTADA! CPF: {cpf} - {dados.get('nome')}")
        
        thread = threading.Thread(target=processar_demissao_async, args=(dados, cpf))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'status': 'aceito',
            'mensagem': 'Webhook recebido. Processamento iniciado em background.',
            'cpf': cpf,
            'colaborador': dados.get('nome')
        })
        
    except Exception as error:
        logger.error(f"[ERRO] Erro no webhook: {str(error)}")
        return jsonify({'status': 'erro', 'erro': str(error)}), 500


def _cpf_ja_processado(cpf):
    """Verifica se o CPF já foi processado recentemente."""
    if cpf not in cpfs_processados:
        return False
    
    ultimo = cpfs_processados[cpf]
    tempo_desde = (datetime.now() - ultimo['timestamp']).total_seconds()
    
    if tempo_desde < TEMPO_BLOQUEIO_DUPLICATA:
        logger.warning(f"[AVISO] CPF {cpf} já processado há {tempo_desde:.0f}s. Ignorando duplicata.")
        return True
    
    return False


if __name__ == '__main__':
    PORT = 3000
    
    print("=" * 60)
    print("🚀 SERVIDOR DE INTEGRAÇÃO SOLIDES")
    print("=" * 60)
    print(f"📡 Servidor: http://localhost:{PORT}")
    print(f"📡 Webhook:  http://localhost:{PORT}/webhook/solides")
    print(f"🔍 Consulta: http://localhost:{PORT}/consulta-ad")
    print(f"📊 Status:   http://localhost:{PORT}/status")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=PORT, debug=True)
