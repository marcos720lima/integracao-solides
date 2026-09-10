import os

from google_admin import GoogleAdminConfigError, obter_service_admin

LIMITE_PAGINAS_SEGURANCA = 25


def _sem_login_registrado(valor):
    return not valor or str(valor).startswith("1970-01-01")


PARTICULAS = {"da", "de", "do", "das", "dos", "e"}


def _limpar(palavra):
    return palavra.replace("'", "").replace('"', "").replace("*", "")


def _montar_query_busca(termo):
    """A Directory API so aceita valor sem espaco depois de 'campo:'. Termo com
    espaco quebra a query (Invalid Input: query), entao ancora na primeira e na
    ultima palavra e o filtro fino fica por conta de _corresponde_ao_termo."""
    palavras = [p for p in termo.split() if p]
    if not palavras:
        return None, []

    primeira = _limpar(palavras[0])
    ultima = _limpar(palavras[-1])
    if not primeira and not ultima:
        return None, []

    if len(palavras) == 1:
        return f"email:{primeira}* OR givenName:{primeira}* OR familyName:{primeira}*", palavras

    partes = []
    if primeira:
        partes.append(f"email:{primeira}*")
        partes.append(f"givenName:{primeira}*")
    if ultima:
        partes.append(f"familyName:{ultima}*")
    return " OR ".join(partes), palavras


def _corresponde_ao_termo(usuario, palavras):
    relevantes = [p for p in palavras if p.lower() not in PARTICULAS]
    if not relevantes:
        return True
    alvo = f"{usuario.get('nome', '')} {usuario.get('email', '')}".lower()
    return all(p.lower() in alvo for p in relevantes)


def listar_usuarios(query=None, max_resultados=500):
    service = obter_service_admin()

    base = {"customer": "my_customer", "maxResults": min(max_resultados, 500), "orderBy": "givenName"}
    palavras_filtro = []
    consulta = None
    if query:
        consulta, palavras_filtro = _montar_query_busca(query.strip())

    if consulta:
        try:
            resultado = _coletar_usuarios(service, dict(base, query=consulta), palavras_filtro, max_resultados)
        except Exception:
            resultado = []
        if resultado:
            return resultado

    # Sem termo, ou a busca do servidor nao achou nada: varre o dominio e filtra aqui.
    return _coletar_usuarios(service, dict(base), palavras_filtro, max_resultados)


def _coletar_usuarios(service, parametros, palavras_filtro, max_resultados):
    usuarios = []
    page_token = None
    paginas = 0

    while True:
        if page_token:
            parametros["pageToken"] = page_token
        resposta = service.users().list(**parametros).execute()

        for u in resposta.get("users", []):
            nome = u.get("name", {})
            ultimo_login = u.get("lastLoginTime")
            usuario = {
                "email": u.get("primaryEmail", ""),
                "nome": nome.get("fullName") or f"{nome.get('givenName', '')} {nome.get('familyName', '')}".strip(),
                "suspenso": bool(u.get("suspended")),
                "admin": bool(u.get("isAdmin")),
                "unidade_organizacional": u.get("orgUnitPath", "/"),
                "ultimo_login": None if _sem_login_registrado(ultimo_login) else ultimo_login,
            }
            if _corresponde_ao_termo(usuario, palavras_filtro):
                usuarios.append(usuario)

        page_token = resposta.get("nextPageToken")
        paginas += 1
        if not page_token or len(usuarios) >= max_resultados or paginas >= LIMITE_PAGINAS_SEGURANCA:
            break

    return usuarios[:max_resultados]


def listar_grupos(max_resultados=500):
    service = obter_service_admin()

    parametros = {"customer": "my_customer", "maxResults": min(max_resultados, 200)}
    grupos = []
    page_token = None
    paginas = 0

    while True:
        if page_token:
            parametros["pageToken"] = page_token
        resposta = service.groups().list(**parametros).execute()

        for g in resposta.get("groups", []):
            grupos.append({
                "email": g.get("email", ""),
                "nome": g.get("name", ""),
                "descricao": g.get("description", ""),
                "quantidade_membros": int(g.get("directMembersCount", 0) or 0),
            })

        page_token = resposta.get("nextPageToken")
        paginas += 1
        if not page_token or len(grupos) >= max_resultados or paginas >= LIMITE_PAGINAS_SEGURANCA:
            break

    grupos.sort(key=lambda g: g["nome"].lower())
    return grupos[:max_resultados]


def listar_membros_grupo(email_grupo):
    service = obter_service_admin()

    membros = []
    page_token = None
    paginas = 0

    while True:
        parametros = {"groupKey": email_grupo, "maxResults": 200}
        if page_token:
            parametros["pageToken"] = page_token
        resposta = service.members().list(**parametros).execute()

        for m in resposta.get("members", []):
            membros.append({
                "email": m.get("email", ""),
                "papel": m.get("role", ""),
                "tipo": m.get("type", ""),
                "status": m.get("status", ""),
            })

        page_token = resposta.get("nextPageToken")
        paginas += 1
        if not page_token or paginas >= LIMITE_PAGINAS_SEGURANCA:
            break

    return membros


def criar_grupo(email_grupo, nome, descricao=""):
    from googleapiclient.errors import HttpError

    service = obter_service_admin()
    corpo = {"email": email_grupo, "name": nome}
    if descricao:
        corpo["description"] = descricao

    try:
        service.groups().insert(body=corpo).execute()
        return True, "Grupo criado com sucesso."
    except HttpError as exc:
        detalhe = getattr(exc, "reason", None) or str(exc)
        return False, f"Falha ao criar o grupo: {detalhe}"


def adicionar_membro_grupo(email_grupo, email_membro, papel="MEMBER"):
    from googleapiclient.errors import HttpError

    service = obter_service_admin()
    try:
        service.members().insert(
            groupKey=email_grupo, body={"email": email_membro, "role": papel},
        ).execute()
        return True, "Membro adicionado com sucesso."
    except HttpError as exc:
        if getattr(exc.resp, "status", None) == 409:
            return False, "Esse email já é membro do grupo."
        detalhe = getattr(exc, "reason", None) or str(exc)
        return False, f"Falha ao adicionar membro: {detalhe}"


def remover_membro_grupo(email_grupo, email_membro):
    from googleapiclient.errors import HttpError

    service = obter_service_admin()
    try:
        service.members().delete(groupKey=email_grupo, memberKey=email_membro).execute()
        return True, "Membro removido com sucesso."
    except HttpError as exc:
        if getattr(exc.resp, "status", None) == 404:
            return False, "Esse email não é membro do grupo."
        detalhe = getattr(exc, "reason", None) or str(exc)
        return False, f"Falha ao remover membro: {detalhe}"


def listar_unidades_organizacionais():
    service = obter_service_admin()
    resposta = service.orgunits().list(customerId="my_customer", type="all").execute()

    unidades = [{
        "caminho": ou.get("orgUnitPath", ""),
        "nome": ou.get("name", ""),
        "descricao": ou.get("description", ""),
        "caminho_pai": ou.get("parentOrgUnitPath", ""),
    } for ou in resposta.get("organizationUnits", [])]

    unidades.sort(key=lambda u: u["caminho"])
    return unidades


def email_existe_no_google(email):
    from googleapiclient.errors import HttpError

    service = obter_service_admin()
    try:
        service.users().get(userKey=email).execute()
        return True
    except HttpError as exc:
        if getattr(exc.resp, "status", None) == 404:
            return False
        raise


def obter_status_google(email):
    from googleapiclient.errors import HttpError

    service = obter_service_admin()
    try:
        usuario = service.users().get(userKey=email).execute()
        return {"existe": True, "suspenso": bool(usuario.get("suspended"))}
    except HttpError as exc:
        if getattr(exc.resp, "status", None) == 404:
            return {"existe": False, "suspenso": None}
        raise


def criar_usuario_google(nome, sobrenome, email, senha, cargo=None, departamento=None, unidade_organizacional=None):
    service = obter_service_admin()

    corpo = {
        "name": {"givenName": nome, "familyName": sobrenome},
        "primaryEmail": email,
        "password": senha,
        "changePasswordAtNextLogin": True,
    }

    if unidade_organizacional:
        corpo["orgUnitPath"] = unidade_organizacional

    organizacao = {}
    if cargo:
        organizacao["title"] = cargo
    if departamento:
        organizacao["department"] = departamento
    if organizacao:
        organizacao["primary"] = True
        corpo["organizations"] = [organizacao]

    return service.users().insert(body=corpo).execute()
