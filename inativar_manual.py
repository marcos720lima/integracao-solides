"""
Script para inativação manual de usuário nos sistemas.

Uso:
    python inativar_manual.py --cpf 01876263245 --email ricardo.farias@unimedoestedopara.coop.br --nome "RICARDO ANDRE FARIAS DE JESUS"

Parâmetros:
    --cpf       CPF do colaborador (usado no GIU)
    --email     Email corporativo (usado nos demais sistemas)
    --nome      Nome completo (usado no Tasy)
    --sistemas  Lista de sistemas para inativar (opcional, padrão: todos)
                Opções: ad, crm, saw, giu, ged, bplus, tasy
    --pular-ad  Pular inativação no Active Directory

Exemplos:
    # Inativar em todos os sistemas
    python inativar_manual.py --cpf 01876263245 --email ricardo.farias@unimedoestedopara.coop.br --nome "RICARDO ANDRE FARIAS DE JESUS"
    
    # Inativar apenas no GIU (só precisa do CPF)
    python inativar_manual.py --cpf 01876263245 --sistemas giu
    
    # Inativar em sistemas específicos
    python inativar_manual.py --email ricardo.farias@unimedoestedopara.coop.br --sistemas crm saw ged
    
    # Inativar em tudo EXCETO o AD
    python inativar_manual.py --cpf 01876263245 --email ricardo.farias@unimedoestedopara.coop.br --pular-ad
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# Cores para o terminal
class Cores:
    VERDE = '\033[92m'
    AMARELO = '\033[93m'
    VERMELHO = '\033[91m'
    AZUL = '\033[94m'
    RESET = '\033[0m'
    NEGRITO = '\033[1m'

def print_titulo(texto):
    print(f"\n{Cores.AZUL}{Cores.NEGRITO}{'='*60}{Cores.RESET}")
    print(f"{Cores.AZUL}{Cores.NEGRITO}{texto.center(60)}{Cores.RESET}")
    print(f"{Cores.AZUL}{Cores.NEGRITO}{'='*60}{Cores.RESET}\n")

def print_sucesso(texto):
    print(f"{Cores.VERDE}[OK] {texto}{Cores.RESET}")

def print_aviso(texto):
    print(f"{Cores.AMARELO}[AVISO] {texto}{Cores.RESET}")

def print_erro(texto):
    print(f"{Cores.VERMELHO}[ERRO] {texto}{Cores.RESET}")

def print_info(texto):
    print(f"{Cores.AZUL}[INFO] {texto}{Cores.RESET}")

# Configuração dos sistemas
SISTEMAS = {
    'ad': {
        'nome': 'Active Directory',
        'requer': ['cpf'],
        'script': None  # Tratamento especial
    },
    'crm': {
        'nome': 'CRM JMJ',
        'requer': ['email'],
        'script': 'rpa_crm.py'
    },
    'saw': {
        'nome': 'SAW',
        'requer': ['email'],
        'script': 'rpa_saw.py'
    },
    'giu': {
        'nome': 'GIU Unimed',
        'requer': ['cpf'],
        'script': 'rpa_giu.py'
    },
    'ged': {
        'nome': 'GED Bye Bye Paper',
        'requer': ['email'],
        'script': 'rpa_ged.py'
    },
    'bplus': {
        'nome': 'B+ Reembolso',
        'requer': ['email'],
        'script': 'rpa_bplus.py'
    },
    'tasy': {
        'nome': 'Tasy EMR',
        'requer': ['nome', 'email'],
        'script': 'rpa_tasy.py'
    }
}

def desativar_ad(cpf):
    """Desativa usuário no Active Directory."""
    try:
        from ldap3 import ALL, Connection, MODIFY_REPLACE, Server
        from ldap3.utils.conv import escape_filter_chars
        
        AD_URL = os.getenv('AD_URL')
        AD_USER = os.getenv('AD_USER')
        AD_PASS = os.getenv('AD_PASS')
        BASE_DN = os.getenv('BASE_DN')
        
        print_info(f"Conectando ao AD: {AD_URL}")
        
        server = Server(AD_URL, get_info=ALL, use_ssl=True)
        conn = Connection(server, user=AD_USER, password=AD_PASS, auto_bind=True)
        
        print_sucesso("Conectado ao AD")
        
        cpf_sanitizado = escape_filter_chars(cpf)
        search_filter = f"(&(objectClass=user)(employeeID={cpf_sanitizado}))"
        conn.search(BASE_DN, search_filter, attributes=['userAccountControl', 'sAMAccountName', 'displayName'])
        
        if not conn.entries:
            conn.unbind()
            return {'status': 'nao_encontrado', 'msg': f'Usuário com CPF {cpf} não encontrado no AD'}
        
        usuario = conn.entries[0]
        nome = usuario.displayName.value if usuario.displayName else usuario.sAMAccountName.value
        
        print_info(f"Usuário encontrado: {nome} ({usuario.sAMAccountName.value})")
        
        user_dn = str(usuario.entry_dn)
        uac_atual = int(str(usuario.userAccountControl.value))
        uac_novo = uac_atual | 0x2
        modificacao = {'userAccountControl': [(MODIFY_REPLACE, [uac_novo])]}
        
        if conn.modify(user_dn, modificacao):
            conn.unbind()
            return {'status': 'sucesso', 'msg': f'Usuário {nome} desativado no AD'}
        else:
            conn.unbind()
            return {'status': 'erro', 'msg': f'Erro ao desativar: {conn.result}'}
            
    except Exception as e:
        return {'status': 'erro', 'msg': str(e)}

def _env_com_node_heap_maior():
    """Configura NODE_OPTIONS para evitar 'heap out of memory' no Playwright."""
    env = os.environ.copy()
    node_options = (env.get("NODE_OPTIONS") or "").strip()
    heap_mb_raw = (os.getenv("PLAYWRIGHT_MAX_OLD_SPACE_SIZE_MB") or "").strip()
    try:
        heap_mb = int(heap_mb_raw) if heap_mb_raw else 4096
    except ValueError:
        heap_mb = 4096
    if "--max-old-space-size" not in node_options:
        extra = f"--max-old-space-size={heap_mb}"
        env["NODE_OPTIONS"] = f"{node_options} {extra}".strip() if node_options else extra
    return env


def executar_rpa(script, args_extra):
    """Executa um script RPA. args_extra deve ser uma lista de argumentos."""
    if not os.path.exists(script):
        return {'status': 'erro', 'msg': f'Script {script} não encontrado'}
    
    if isinstance(args_extra, str):
        args_extra = [args_extra]
    
    try:
        cmd_args = [sys.executable, script] + args_extra

        process = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=os.getcwd(),
            shell=False,
            stdin=subprocess.DEVNULL,
            env=_env_com_node_heap_maior()
        )
        
        codigo = process.returncode
        
        if codigo == 0:
            return {'status': 'sucesso', 'msg': 'Desativado com sucesso'}
        elif codigo == 2:
            return {'status': 'ja_inativo', 'msg': 'Usuário já estava inativo'}
        elif codigo == 3:
            return {'status': 'nao_encontrado', 'msg': 'Usuário não possui acesso'}
        else:
            erro = process.stderr.strip() if process.stderr else 'Erro desconhecido'
            return {'status': 'erro', 'msg': erro[:100]}
            
    except subprocess.TimeoutExpired:
        return {'status': 'erro', 'msg': 'Timeout (300s)'}
    except Exception as e:
        return {'status': 'erro', 'msg': str(e)}

def processar_sistema(sistema_id, cpf=None, email=None, nome=None):
    """Processa a inativação em um sistema específico."""
    config = SISTEMAS.get(sistema_id)
    if not config:
        return {'status': 'erro', 'msg': f'Sistema {sistema_id} não configurado'}
    
    nome_sistema = config['nome']
    print(f"\n{'─'*50}")
    print(f"{Cores.NEGRITO}Processando: {nome_sistema}{Cores.RESET}")
    
    # Verificar parâmetros necessários
    for req in config['requer']:
        if req == 'cpf' and not cpf:
            print_aviso(f"CPF não informado - pulando {nome_sistema}")
            return {'status': 'pulado', 'msg': 'CPF não informado'}
        if req == 'email' and not email:
            print_aviso(f"Email não informado - pulando {nome_sistema}")
            return {'status': 'pulado', 'msg': 'Email não informado'}
        if req == 'nome' and not nome:
            print_aviso(f"Nome não informado - pulando {nome_sistema}")
            return {'status': 'pulado', 'msg': 'Nome não informado'}
    
    if sistema_id == 'ad':
        resultado = desativar_ad(cpf)
    elif sistema_id == 'giu':
        resultado = executar_rpa(config['script'], [cpf])
    elif sistema_id == 'tasy':
        nome_conta = email.split('@')[0] if email else ''
        resultado = executar_rpa(config['script'], [nome, nome_conta])
    elif sistema_id == 'bplus':
        resultado = executar_rpa(config['script'], [email])
    else:
        resultado = executar_rpa(config['script'], [email])
    
    # Mostrar resultado
    status = resultado['status']
    msg = resultado['msg']
    
    if status == 'sucesso':
        print_sucesso(f"{nome_sistema}: {msg}")
    elif status == 'ja_inativo':
        print_aviso(f"{nome_sistema}: {msg}")
    elif status == 'nao_encontrado':
        print_info(f"{nome_sistema}: {msg}")
    else:
        print_erro(f"{nome_sistema}: {msg}")
    
    return resultado

def converter_resultados_para_formato_server(resultados):
    """Converte os resultados do script manual para o formato esperado pelo server.py."""
    detalhes = []
    
    for sistema_id, resultado in resultados.items():
        if sistema_id == 'ad':
            continue  # AD é tratado separadamente
            
        config = SISTEMAS.get(sistema_id, {})
        nome_sistema = config.get('nome', sistema_id.upper())
        status = resultado.get('status', 'erro')
        
        # Converter status para formato do server.py
        if status == 'sucesso':
            status_server = 'sucesso'
        elif status == 'ja_inativo':
            status_server = 'ja_inativo'
        elif status == 'nao_encontrado':
            status_server = 'nao_encontrado'
        elif status == 'pulado':
            status_server = 'skipped'
        else:
            status_server = 'erro'
        
        detalhes.append({
            'sistema': nome_sistema,
            'status': status_server,
            'erro': resultado.get('msg', '') if status == 'erro' else None
        })
    
    return {'detalhes': detalhes}


def enviar_email_notificacao_manual(cpf, email, nome, resultados):
    """Envia email de notificação usando a mesma função do server.py."""
    print_info("Enviando email de notificação...")
    
    try:
        # Importar função do server.py
        from server import enviar_email_notificacao
        
        # Montar dados do colaborador no formato esperado
        dados_colaborador = {
            'nome': nome or 'N/A',
            'email': email or 'N/A',
            'documentos': {'cpf': cpf},
            'departamento': {'nome': 'N/A'},
            'cargo': {'nome': 'N/A'},
            'matricula': 'N/A',
            'data_demissao': datetime.now().strftime('%d/%m/%Y')
        }
        
        # Montar resultado do AD
        resultado_ad_info = resultados.get('ad', {})
        if resultado_ad_info.get('status') == 'sucesso':
            resultado_ad = {
                'cpf': cpf,
                'login': 'N/A',
                'nome': nome or 'N/A',
                'employeeID': cpf,
                'status': 'desativado'
            }
        else:
            resultado_ad = {
                'cpf': cpf,
                'status': resultado_ad_info.get('status', 'erro'),
                'erro': resultado_ad_info.get('msg', '')
            }
        
        # Converter resultados dos sistemas
        resultado_sistemas = converter_resultados_para_formato_server(resultados)
        
        # Enviar email
        enviar_email_notificacao(dados_colaborador, resultado_ad, resultado_sistemas)
        
        print_sucesso("Email enviado com sucesso!")
        return True
        
    except Exception as e:
        print_erro(f"Erro ao enviar email: {str(e)}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Inativação manual de usuário nos sistemas',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python inativar_manual.py --cpf 01876263245 --email ricardo.farias@unimedoestedopara.coop.br
  python inativar_manual.py --cpf 01876263245 --sistemas giu
  python inativar_manual.py --email usuario@empresa.com --sistemas crm saw ged
        """
    )
    
    parser.add_argument('--cpf', help='CPF do colaborador (somente números)')
    parser.add_argument('--email', help='Email corporativo')
    parser.add_argument('--nome', help='Nome completo (para Tasy)')
    parser.add_argument('--sistemas', nargs='+', 
                        choices=['ad', 'crm', 'saw', 'giu', 'ged', 'bplus', 'tasy'],
                        help='Sistemas específicos para inativar')
    parser.add_argument('--pular-ad', action='store_true', 
                        help='Pular inativação no Active Directory')
    parser.add_argument('--enviar-email', action='store_true',
                        help='Enviar email de notificação para o TI')
    
    args = parser.parse_args()
    
    # Validar parâmetros mínimos
    if not args.cpf and not args.email:
        print_erro("Informe pelo menos --cpf ou --email")
        parser.print_help()
        sys.exit(1)
    
    # Definir sistemas a processar
    if args.sistemas:
        sistemas_processar = args.sistemas
    else:
        sistemas_processar = ['ad', 'crm', 'saw', 'giu', 'ged', 'bplus', 'tasy']
    
    if args.pular_ad and 'ad' in sistemas_processar:
        sistemas_processar.remove('ad')
    
    # Cabeçalho
    print_titulo("INATIVAÇÃO MANUAL DE USUÁRIO")
    print(f"Data/Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"CPF: {args.cpf or 'Não informado'}")
    print(f"Email: {args.email or 'Não informado'}")
    print(f"Nome: {args.nome or 'Não informado'}")
    print(f"Sistemas: {', '.join(sistemas_processar)}")
    
    # Processar cada sistema
    resultados = {}
    for sistema in sistemas_processar:
        resultados[sistema] = processar_sistema(
            sistema,
            cpf=args.cpf,
            email=args.email,
            nome=args.nome
        )
    
    # Resumo final
    print_titulo("RESUMO")
    
    sucessos = sum(1 for r in resultados.values() if r['status'] == 'sucesso')
    ja_inativos = sum(1 for r in resultados.values() if r['status'] == 'ja_inativo')
    nao_encontrados = sum(1 for r in resultados.values() if r['status'] == 'nao_encontrado')
    erros = sum(1 for r in resultados.values() if r['status'] == 'erro')
    pulados = sum(1 for r in resultados.values() if r['status'] == 'pulado')
    
    print(f"{Cores.VERDE}Sucesso: {sucessos}{Cores.RESET}")
    print(f"{Cores.AMARELO}Já inativos: {ja_inativos}{Cores.RESET}")
    print(f"{Cores.AZUL}Não encontrados: {nao_encontrados}{Cores.RESET}")
    print(f"{Cores.AMARELO}Pulados: {pulados}{Cores.RESET}")
    print(f"{Cores.VERMELHO}Erros: {erros}{Cores.RESET}")
    
    # Enviar email se solicitado
    if args.enviar_email:
        print(f"\n{'─'*50}")
        enviar_email_notificacao_manual(args.cpf, args.email, args.nome, resultados)

    print(f"\n{'='*60}\n")
    
    if erros > 0:
        sys.exit(1)
    sys.exit(0)

if __name__ == '__main__':
    main()
