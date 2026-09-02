from ldap3 import ALL, Connection, Server
from ldap3.utils.conv import escape_filter_chars

DESCRICAO_LIBERADA = "TI"


class ErroAutenticacao(Exception):
    pass


def autenticar_usuario(login, senha):
    from server import AD_URL, AD_USER, AD_PASS, BASE_DN

    login = (login or "").strip()

    if not login or not senha:
        raise ErroAutenticacao("Informe usuário e senha.")

    if not all([AD_URL, AD_USER, AD_PASS, BASE_DN]):
        raise ErroAutenticacao("Conexão com o Active Directory não está configurada (.env).")

    servidor = Server(AD_URL, get_info=ALL, use_ssl=True)

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

    try:
        conn_usuario = Connection(
            servidor, user=user_dn, password=senha,
            auto_bind=True, authentication="SIMPLE"
        )
        conn_usuario.unbind()
    except Exception:
        raise ErroAutenticacao("Usuário ou senha inválidos.")

    if DESCRICAO_LIBERADA.lower() not in descricao.lower():
        raise ErroAutenticacao("Seu usuário não tem permissão para acessar este painel.")

    return {
        "login": login,
        "nome": nome,
        "email": email,
        "descricao": descricao,
    }
