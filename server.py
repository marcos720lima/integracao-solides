from flask import Flask, request, jsonify
from flask_cors import CORS
from ldap3 import Server, Connection, ALL, MODIFY_REPLACE
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
import re
from datetime import datetime
import logging
import subprocess
import os
import threading

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

app = Flask(__name__)

cors = CORS(app, resources={
    r"/*": {
        "origins": ["*"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

SISTEMAS_CONFIG = {
    'crm_jmj': {
        'ativo': True,
        'script': 'rpa_crm.py',
        'timeout': 300,
        'nome': 'CRM JMJ'
    },
    'saw': {
        'ativo': True,
        'script': 'rpa_saw.py', 
        'timeout': 300,
        'nome': 'SAW'
    },
    'giu': {
        'ativo': True,
        'script': 'rpa_giu.py',
        'timeout': 300,
        'nome': 'GIU Unimed'
    },
    'ged': {
        'ativo': True,
        'script': 'rpa_ged.py',
        'timeout': 300,
        'nome': 'GED Bye Bye Paper'
    },
    'sso_email': {
        'ativo': False,
        'script': 'rpa_sso_email.py',
        'timeout': 300,
        'nome': 'SSO Email Unimed'
    },
    'nextqs': {
        'ativo': True,
        'script': 'rpa_nextqs.py',
        'timeout': 300,
        'nome': 'NextQS Manager'
    },
    'bplus': {
        'ativo': True,
        'script': 'rpa_bplus.py',
        'timeout': 300,
        'nome': 'B+ Reembolso'
    }
}

def executar_sistema_rpa(sistema_id, email_usuario, cpf_usuario=None):
    try:
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
        
        # GIU usa CPF, outros sistemas usam email
        if sistema_id == 'giu' and cpf_usuario:
            parametro = cpf_usuario
            logger.info(f"[RPA] Executando {nome} para CPF: {cpf_usuario}")
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
        
        cmd = f'python {script} "{parametro}"'
        
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd(),
            shell=True
        )
        
        # Interpretar códigos de retorno:
        # 0 = sucesso, 1 = erro, 2 = já inativo, 3 = não encontrado
        codigo = process.returncode
        
        if codigo == 0:
            logger.info(f"[OK] {nome}: Desativado com sucesso!")
            return {
                'status': 'sucesso',
                'sistema': nome,
                'log': process.stdout
            }
        elif codigo == 2:
            logger.info(f"[AVISO] {nome}: Já estava inativo/bloqueado")
            return {
                'status': 'ja_inativo',
                'sistema': nome,
                'log': process.stdout
            }
        elif codigo == 3:
            logger.info(f"[INFO] {nome}: Usuário não possui acesso")
            return {
                'status': 'nao_encontrado',
                'sistema': nome,
                'log': process.stdout
            }
        else:
            logger.error(f"[ERRO] Erro no {nome}: {process.stderr}")
            return {
                'status': 'erro',
                'sistema': nome,
                'erro': process.stderr,
                'log': process.stdout
            }
            
    except subprocess.TimeoutExpired:
        logger.error(f"[ERRO] Timeout no {nome}")
        return {
            'status': 'erro',
            'sistema': config['nome'],
            'erro': f'Timeout de {timeout}s excedido'
        }
    except Exception as e:
        logger.error(f"[ERRO] Exceção no {sistema_id}: {str(e)}")
        return {
            'status': 'erro',
            'sistema': sistema_id,
            'erro': str(e)
        }


def limpar_cpf(cpf):
    if not cpf:
        return None
    return re.sub(r'[.\-\s]', '', cpf)

def formatar_cpf(cpf):
    if not cpf:
        return 'N/A'
    cpf_limpo = limpar_cpf(cpf)
    if not cpf_limpo or len(cpf_limpo) != 11:
        return cpf
    return f"{cpf_limpo[:3]}.{cpf_limpo[3:6]}.{cpf_limpo[6:9]}-{cpf_limpo[9:]}"

def desativar_usuario_por_cpf(cpf):
    try:
        logger.info(f"[PROC] Iniciando desativação do usuário com CPF: {cpf}")
        
        server = Server(AD_URL, get_info=ALL, use_ssl=True)
        conn = Connection(
            server, 
            user=AD_USER, 
            password=AD_PASS, 
            auto_bind=True,
            authentication='SIMPLE'
        )
        
        logger.info("Conectado no AD para desativação")
        
        search_filter = f"(&(objectClass=user)(employeeID={cpf}))"
        attributes = ['userAccountControl', 'sAMAccountName', 'employeeID', 'cn', 'displayName']
        
        conn.search(
            BASE_DN, 
            search_filter, 
            attributes=attributes
        )
        
        if not conn.entries:
            raise Exception(f"Usuário com CPF/EmployeeID {cpf} não encontrado no AD")
        
        usuario = conn.entries[0]
        
        logger.info(f"👤 Usuário encontrado para desativação:")
        logger.info(f"   - Nome: {usuario.displayName.value if usuario.displayName else usuario.cn.value}")
        logger.info(f"   - Login: {usuario.sAMAccountName.value}")
        logger.info(f"   - EmployeeID: {usuario.employeeID.value}")
        
        user_dn = str(usuario.entry_dn)
        modificacao = {'userAccountControl': [(MODIFY_REPLACE, [514])]}
        
        success = conn.modify(user_dn, modificacao)
        
        if not success:
            raise Exception(f"Erro ao desativar usuário: {conn.result}")
        
        logger.info(f"[OK] Usuário {usuario.sAMAccountName.value} (CPF: {cpf}) desativado com sucesso no AD")
        
        resultado = {
            'cpf': cpf,
            'login': usuario.sAMAccountName.value,
            'nome': usuario.displayName.value if usuario.displayName else usuario.cn.value,
            'employeeID': usuario.employeeID.value,
            'dn': user_dn,
            'status': 'desativado'
        }
        
        conn.unbind()
        return resultado
        
    except Exception as e:
        logger.error(f"[ERRO] Erro ao desativar usuário: {str(e)}")
        if 'conn' in locals():
            conn.unbind()
        raise e

def consultar_email_por_cpf(cpf):
    try:
        logger.info(f"[EMAIL] Consultando email no AD para CPF: {cpf}")
        
        server = Server(AD_URL, get_info=ALL, use_ssl=True)
        conn = Connection(
            server, 
            user=AD_USER, 
            password=AD_PASS, 
            auto_bind=True,
            authentication='SIMPLE'
        )
        
        search_filter = f"(&(objectClass=user)(employeeID={cpf}))"
        attributes = ['mail', 'userPrincipalName', 'sAMAccountName']
        
        conn.search(BASE_DN, search_filter, attributes=attributes)
        
        if conn.entries:
            usuario = conn.entries[0]
            email = None
            
            if usuario.mail and usuario.mail.value:
                email = str(usuario.mail.value)
            elif usuario.userPrincipalName and usuario.userPrincipalName.value:
                email = str(usuario.userPrincipalName.value)
            elif usuario.sAMAccountName and usuario.sAMAccountName.value:
                email = f"{usuario.sAMAccountName.value}@unimedoestedopara.coop.br"
            
            conn.unbind()
            logger.info(f"[EMAIL] Email encontrado: {email}")
            return email
        else:
            conn.unbind()
            raise Exception(f"Usuário com CPF {cpf} não encontrado")
            
    except Exception as e:
        logger.error(f"[ERRO] Erro ao consultar email: {str(e)}")
        if 'conn' in locals():
            conn.unbind()
        raise e

def enviar_email_notificacao(dados_colaborador, resultado_ad, resultado_sistemas=None):
    try:
        logger.info("[EMAIL] [EMAIL] Iniciando envio de notificação...")
        
        server = smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port'])
        server.starttls()
        server.login(EMAIL_CONFIG['username'], EMAIL_CONFIG['password'])
        
        logger.info("[OK] [EMAIL] Conexão SMTP estabelecida")
        
        cpf_correto = resultado_ad.get('cpf') or dados_colaborador.get('documentos', {}).get('cpf', 'N/A')
        cpf_formatado = formatar_cpf(cpf_correto)
        
        status_ad = "Desativado" if resultado_ad.get('status') == 'desativado' else "Erro ao Desativar"
        status_jmj = "Não executado"
        status_saw = "Não executado"
        status_giu = "Não executado"
        status_ged = "Não executado"
        status_nextqs = "Não executado"
        status_bplus = "Não executado"
        
        def obter_status_formatado(sistema):
            status = sistema.get('status')
            if status == 'sucesso':
                return "Desativado"
            elif status == 'ja_inativo':
                return "Já estava inativo"
            elif status == 'nao_encontrado':
                return "Não possui acesso"
            elif status == 'erro':
                return f"Erro: {sistema.get('erro', 'Erro desconhecido')[:40]}"
            else:
                return "Não executado"
        
        if resultado_sistemas and resultado_sistemas.get('detalhes'):
            for sistema in resultado_sistemas.get('detalhes', []):
                nome_sistema = sistema.get('sistema', '').upper()
                if 'JMJ' in nome_sistema or 'CRM' in nome_sistema:
                    status_jmj = obter_status_formatado(sistema)
                elif 'SAW' in nome_sistema:
                    status_saw = obter_status_formatado(sistema)
                elif 'GIU' in nome_sistema:
                    status_giu = obter_status_formatado(sistema)
                elif 'GED' in nome_sistema or 'BYE' in nome_sistema:
                    s = sistema.get('status')
                    if s == 'sucesso':
                        status_ged = "Bloqueado"
                    elif s == 'ja_inativo':
                        status_ged = "Já estava bloqueado"
                    elif s == 'nao_encontrado':
                        status_ged = "Não possui acesso"
                    elif s == 'erro':
                        status_ged = f"Erro: {sistema.get('erro', 'Erro')[:40]}"
                elif 'NEXTQS' in nome_sistema:
                    status_nextqs = obter_status_formatado(sistema)
                elif 'BPLUS' in nome_sistema or 'B+' in nome_sistema or 'REEMBOLSO' in nome_sistema:
                    status_bplus = obter_status_formatado(sistema)
        
        nome_colaborador = dados_colaborador.get('nome', 'N/A')
        setor = dados_colaborador.get('departamento', {}).get('nome', 'N/A')
        cargo = dados_colaborador.get('cargo', {}).get('nome', 'N/A')
        
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                h2 {{ color: #c0392b; border-bottom: 2px solid #c0392b; padding-bottom: 10px; }}
                h3 {{ color: #2c3e50; margin-top: 25px; }}
                .info-box {{ background-color: #f8f9fa; padding: 15px; border-radius: 8px; margin: 10px 0; }}
                .status-box {{ background-color: #fff3cd; padding: 15px; border-radius: 8px; margin: 10px 0; border-left: 4px solid #ffc107; }}
                .success {{ color: #27ae60; }}
                .error {{ color: #c0392b; }}
                .warning {{ color: #f39c12; }}
                table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
                td {{ padding: 8px 12px; border-bottom: 1px solid #ddd; }}
                td:first-child {{ font-weight: bold; width: 40%; background-color: #f8f9fa; }}
                .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>NOTIFICAÇÃO: Colaborador Demitido - {nome_colaborador}</h2>
                
                <h3>Informações do Colaborador</h3>
                <div class="info-box">
                    <table>
                        <tr><td>Nome:</td><td>{nome_colaborador}</td></tr>
                        <tr><td>CPF:</td><td>{cpf_formatado}</td></tr>
                        <tr><td>Email:</td><td>{dados_colaborador.get('email', 'N/A')}</td></tr>
                        <tr><td>Setor:</td><td>{setor}</td></tr>
                        <tr><td>Cargo:</td><td>{cargo}</td></tr>
                        <tr><td>Matrícula:</td><td>{dados_colaborador.get('matricula', 'N/A')}</td></tr>
                        <tr><td>Data Demissão:</td><td>{dados_colaborador.get('data_demissao', 'N/A')}</td></tr>
                    </table>
                </div>
                
                <h3>Inativações Realizadas</h3>
                <div class="status-box">
                    <table>
                        <tr><td>AD (Active Directory):</td><td>{status_ad}</td></tr>
                        <tr><td>CRM JMJ:</td><td>{status_jmj}</td></tr>
                        <tr><td>SAW:</td><td>{status_saw}</td></tr>
                        <tr><td>GIU Unimed:</td><td>{status_giu}</td></tr>
                        <tr><td>GED (Bye Bye Paper):</td><td>{status_ged}</td></tr>
                        <tr><td>NextQS Manager:</td><td>{status_nextqs}</td></tr>
                        <tr><td>B+ Reembolso:</td><td>{status_bplus}</td></tr>
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
                    <li>Usuário foi automaticamente desativado no Active Directory</li>
                    <li>Verificar acesso a sistemas integrados</li>
                    <li>Confirmar desativação do email corporativo</li>
                    <li>Revogar acessos VPN e sistemas externos</li>
                    <li>Recolher equipamentos corporativos</li>
                </ul>
                
                <div class="footer">
                    <p><em>Esta é uma notificação automática do sistema de integração Solides + Active Directory.</em></p>
                    <p><em>Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}</em></p>
                </div>
            </div>
        </body>
        </html>
        """
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"NOTIFICAÇÃO: Colaborador Demitido - {nome_colaborador}"
        msg['From'] = EMAIL_CONFIG['username']
        msg['To'] = ', '.join(TI_EMAILS)
        
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)
        server.send_message(msg)
        server.quit()
        
        logger.info("[OK] [EMAIL] Email enviado com sucesso!")
        logger.info(f"[EMAIL] [EMAIL] Destinatários: {', '.join(TI_EMAILS)}")
        
        return {'status': 'success', 'recipients': TI_EMAILS}
        
    except Exception as e:
        logger.error(f"[ERRO] Erro ao enviar email: {str(e)}")
        raise e

@app.route('/consulta-ad', methods=['POST'])
def consulta_ad():
    try:
        data = request.get_json()
        login = data.get('login')
        
        logger.info(f"🚀 Iniciando consulta AD para login: {login}")
        
        if not login:
            return jsonify({'error': 'Informe o login (sAMAccountName)'}), 400
        
        server = Server(AD_URL, get_info=ALL, use_ssl=True)
        conn = Connection(
            server, 
            user=AD_USER, 
            password=AD_PASS, 
            auto_bind=True,
            authentication='SIMPLE'
        )
        
        logger.info("[OK] Conectado com sucesso no AD")
        
        search_filter = f"(&(objectClass=user)(sAMAccountName={login}))"
        attributes = [
            'cn', 'displayName', 'givenName', 'sn', 'sAMAccountName',
            'mail', 'employeeID', 'employeeNumber', 'department',
            'title', 'telephoneNumber', 'memberOf'
        ]
        
        conn.search(BASE_DN, search_filter, attributes=attributes)
        
        if not conn.entries:
            conn.unbind()
            return jsonify({
                'error': 'Usuário não encontrado',
                'login_buscado': login,
                'base_dn': BASE_DN,
                'filtro_usado': search_filter
            }), 404
        
        usuario = conn.entries[0]
        logger.info("[OK] Usuário encontrado!")
        
        dados_organizados = {
            'success': True,
            'informacoes_principais': {
                'nome_completo': str(usuario.displayName.value) if usuario.displayName else str(usuario.cn.value),
                'email': str(usuario.mail.value) if usuario.mail else None,
                'employee_id': str(usuario.employeeID.value) if usuario.employeeID else str(usuario.employeeNumber.value) if usuario.employeeNumber else None,
                'login': str(usuario.sAMAccountName.value),
                'primeiro_nome': str(usuario.givenName.value) if usuario.givenName else None,
                'sobrenome': str(usuario.sn.value) if usuario.sn else None,
                'departamento': str(usuario.department.value) if usuario.department else None,
                'cargo': str(usuario.title.value) if usuario.title else None,
                'telefone': str(usuario.telephoneNumber.value) if usuario.telephoneNumber else None,
                'dn': str(usuario.entry_dn)
            },
            'total_encontrados': len(conn.entries)
        }
        
        conn.unbind()
        return jsonify(dados_organizados)
        
    except Exception as e:
        logger.error(f"[ERRO] Erro na consulta AD: {str(e)}")
        return jsonify({'error': str(e)}), 500

def processar_demissao_async(dados, cpf):
    """Processa a demissão em background"""
    try:
        logger.info("🏢 PASSO 1: Desativando usuário no Active Directory...")
        resultado_ad = desativar_usuario_por_cpf(cpf)
        logger.info(f"[OK] Usuário desativado no AD: {resultado_ad}")
        
        email_usuario = None
        if 'mail' in resultado_ad:
            email_usuario = resultado_ad.get('mail')
        elif 'email' in resultado_ad:
            email_usuario = resultado_ad.get('email')
        
        if not email_usuario:
            try:
                email_usuario = consultar_email_por_cpf(cpf)
            except:
                email_usuario = dados.get('email')
        
        logger.info(f"[EMAIL] Email capturado: {email_usuario}")
        
        logger.info("[RPA] PASSO 2: Desativando usuário nos sistemas externos...")
        resultado_sistemas = {
            'total_sistemas': 0,
            'sucessos': 0, 
            'erros': 0,
            'detalhes': [],
            'status_geral': 'sucesso'
        }
        
        for sistema_id, config in SISTEMAS_CONFIG.items():
            if config['ativo']:
                resultado_sistemas['total_sistemas'] += 1
                logger.info(f"[PROC] Processando {config['nome']}...")
                
                resultado_rpa = executar_sistema_rpa(sistema_id, email_usuario, cpf)
                resultado_sistemas['detalhes'].append(resultado_rpa)
                
                if resultado_rpa['status'] == 'sucesso':
                    resultado_sistemas['sucessos'] += 1
                elif resultado_rpa['status'] == 'erro':
                    resultado_sistemas['erros'] += 1
        
        if resultado_sistemas['erros'] > 0 and resultado_sistemas['sucessos'] > 0:
            resultado_sistemas['status_geral'] = 'parcial'
        elif resultado_sistemas['erros'] > 0 and resultado_sistemas['sucessos'] == 0:
            resultado_sistemas['status_geral'] = 'erro'
        
        logger.info("[EMAIL] PASSO 3: Enviando email de notificação...")
        try:
            enviar_email_notificacao(dados, resultado_ad, resultado_sistemas)
            logger.info("[OK] Email de notificação enviado com sucesso!")
        except Exception as email_error:
            logger.error(f"[ERRO] ERRO ao enviar email: {str(email_error)}")
        
        logger.info(f"[OK] Processamento completo para CPF: {cpf}")
        
    except Exception as e:
        logger.error(f"[ERRO] Erro no processamento async: {str(e)}")
    finally:
        if cpf in cpfs_processados:
            cpfs_processados[cpf]['processando'] = False

@app.route('/webhook/solides', methods=['POST'])
def webhook_solides():
    try:
        logger.info("[WEBHOOK] Webhook recebido do Solides")
        
        # Validar WEBHOOK_SECRET
        secret_recebido = request.headers.get('X-Webhook-Secret')
        if WEBHOOK_SECRET and secret_recebido != WEBHOOK_SECRET:
            logger.warning(f"[AVISO] Webhook rejeitado - Secret inválido")
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
        
        agora = datetime.now()
        if cpf in cpfs_processados:
            ultimo = cpfs_processados[cpf]
            tempo_desde = (agora - ultimo['timestamp']).total_seconds()
            
            if tempo_desde < TEMPO_BLOQUEIO_DUPLICATA:
                logger.warning(f"[AVISO] CPF {cpf} já processado há {tempo_desde:.0f}s. Ignorando duplicata.")
                return jsonify({
                    'status': 'ignorado',
                    'motivo': 'CPF já processado recentemente',
                    'cpf': cpf,
                    'segundos_desde_ultimo': tempo_desde
                })
        
        cpfs_processados[cpf] = {'timestamp': agora, 'processando': True}
        
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

@app.route('/sistemas/status', methods=['GET'])
def status_sistemas():
    try:
        sistemas_info = [
            {'id': sid, 'nome': cfg['nome'], 'script': cfg['script'], 'ativo': cfg['ativo']}
            for sid, cfg in SISTEMAS_CONFIG.items()
        ]
        
        return jsonify({
            'status': 'online',
            'total_sistemas': len(sistemas_info),
            'ativos': sum(1 for s in sistemas_info if s['ativo']),
            'sistemas': sistemas_info
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    return jsonify({
        'status': 'online',
        'servico': 'Integração Solides - AD + CRM + SAW',
        'versao': '2.0',
        'timestamp': datetime.now().isoformat(),
        'endpoints': {
            '/webhook/solides': 'POST - Webhook principal (AD + CRM + SAW + Email)',
            '/consulta-ad': 'POST - Consultar usuário no AD',
            '/sistemas/status': 'GET - Status dos sistemas',
            '/status': 'GET - Status do serviço'
        }
    })

if __name__ == '__main__':
    PORT = 3000
    print(f"🚀 Servidor rodando em http://localhost:{PORT}")
    print(f"📡 Webhook Solides: http://localhost:{PORT}/webhook/solides")
    print(f"🔍 Consulta AD: http://localhost:{PORT}/consulta-ad")
    print(f"📊 Status: http://localhost:{PORT}/status")
    
    app.run(host='0.0.0.0', port=PORT, debug=True)

