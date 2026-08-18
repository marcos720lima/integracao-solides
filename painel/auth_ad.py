"""
Autenticação de usuários do painel web via Active Directory (LDAP).

Reaproveita a mesma configuração de conexão (AD_URL, AD_USER, AD_PASS, BASE_DN)
já usada em server.py para consultas administrativas - não é preciso nenhuma
credencial nova no .env.

Fluxo:
    1. Usa a conta de serviço (AD_USER/AD_PASS) só para localizar o usuário
       pelo login (sAMAccountName) e ler o atributo "description".
    2. Valida a senha informada tentando um bind no AD com o DN do próprio
       usuário - se o bind falhar, a senha está incorreta.
    3. Só libera o acesso se o campo "description" do usuário no AD contiver
       o texto configurado em DESCRICAO_LIBERADA (por padrão, "TI").
"""

from ldap3 import ALL, Connection, Server
from ldap3.utils.conv import escape_filter_chars

# Trecho que precisa constar na "descrição" do usuário no AD para liberar o
# acesso ao painel. Ajuste aqui se no seu AD o time de TI usa outro texto.
DESCRICAO_LIBERADA = "TI"


class ErroAutenticacao(Exception):
    """Erro de autenticação (usuário/senha inválidos ou sem permissão de acesso)."""


def autenticar_usuario(login, senha):
    """
    Valida login/senha diretamente no Active Directory e confere se o usuário
    tem permissão para acessar o painel.

    Retorna um dict com os dados do usuário autenticado ou levanta ErroAutenticacao.
    """
    # Import tardio evita import circular (server.py importa este módulo indiretamente).
    from server import AD_URL, AD_USER, AD_PASS, BASE_DN

    login = (login or "").strip()

    if not login or not senha:
        raise ErroAutenticacao("Informe usuário e senha.")

    if not all([AD_URL, AD_USER, AD_PASS, BASE_DN]):
        raise ErroAutenticacao("Conexão com o Active Directory não está configurada (.env).")

    servidor = Server(AD_URL, get_info=ALL, use_ssl=True)

    # 1) Conta de serviço: só para localizar o usuário e ler a descrição
    conn_servico = Connection(
        servidor, user=AD_USER, password=AD_PASS,
        auto_bind=True, authentication="SIMPLE"
    )
    try:
        login_sanitizado = escape_filter_chars(login)
        filtro = f"(&(objectClass=user)(sAMAccountName={login_sanitizado}))"
        conn_servico.search(
            BASE_DN, filtro,
            attributes=["displayName", "description", "sAMAccountName", "mail"]
        )

        if not conn_servico.entries:
            raise ErroAutenticacao("Usuário ou senha inválidos.")

        usuario = conn_servico.entries[0]
        user_dn = str(usuario.entry_dn)
        descricao = str(usuario.description.value) if usuario.description else ""
        nome = str(usuario.displayName.value) if usuario.displayName else login
        email = str(usuario.mail.value) if usuario.mail else None
    finally:
        conn_servico.unbind()

    # 2) Valida a senha do próprio usuário fazendo o bind com as credenciais informadas
    try:
        conn_usuario = Connection(
            servidor, user=user_dn, password=senha,
            auto_bind=True, authentication="SIMPLE"
        )
        conn_usuario.unbind()
    except Exception:
        raise ErroAutenticacao("Usuário ou senha inválidos.")

    # 3) Só libera quem tem "TI" na descrição do AD
    if DESCRICAO_LIBERADA.lower() not in descricao.lower():
        raise ErroAutenticacao("Seu usuário não tem permissão para acessar este painel.")

    return {
        "login": login,
        "nome": nome,
        "email": email,
        "descricao": descricao,
    }
