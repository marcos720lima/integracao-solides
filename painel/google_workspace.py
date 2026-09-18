import os

from google_admin import GoogleAdminConfigError, obter_service_admin, obter_service_licensing, obter_service_reseller

LIMITE_PAGINAS_SEGURANCA = 25
PRODUTO_WORKSPACE = "Google-Apps"
SKU_BUSINESS_STARTER = "1010020027"


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


def listar_grupos_do_usuario(email):
    """Lista os grupos de email que um usuario especifico participa.

    A API do Google exige que 'userKey' seja usado SOZINHO — nao aceita
    'customer' junto (erro 400 'Cannot be used with the customer parameter').
    """
    service = obter_service_admin()

    grupos = []
    page_token = None
    paginas = 0

    while True:
        parametros = {"userKey": email, "maxResults": 200}
        if page_token:
            parametros["pageToken"] = page_token
        resposta = service.groups().list(**parametros).execute()

        for g in resposta.get("groups", []):
            grupos.append({
                "email": g.get("email", ""),
                "nome": g.get("name", ""),
            })

        page_token = resposta.get("nextPageToken")
        paginas += 1
        if not page_token or paginas >= LIMITE_PAGINAS_SEGURANCA:
            break

    grupos.sort(key=lambda g: g["nome"].lower())
    return grupos


def remover_de_todos_os_grupos(email):
    """Remove o usuario de todos os grupos de email que participa.

    Usado antes de suspender a conta (inativação). Continua tentando mesmo se
    uma remoção específica falhar, e devolve o resultado de cada grupo para
    quem chamou decidir o que fazer com falhas parciais.
    """
    try:
        grupos = listar_grupos_do_usuario(email)
    except Exception as exc:
        return [{"grupo": None, "ok": False, "mensagem": f"Falha ao listar grupos do usuário: {exc}"}]

    resultados = []
    for g in grupos:
        ok, mensagem = remover_membro_grupo(g["email"], email)
        resultados.append({"grupo": g["email"], "ok": ok, "mensagem": mensagem})
    return resultados


def obter_usuario_detalhado(email):
    """Busca o perfil completo de um usuário — inclui setor/cargo, que a
    listagem básica de listar_usuarios() não traz (precisa de projection=full)."""
    service = obter_service_admin()
    u = service.users().get(userKey=email, projection="full").execute()

    nome = u.get("name", {})
    organizacoes = u.get("organizations") or []
    org_principal = next((o for o in organizacoes if o.get("primary")),
                          organizacoes[0] if organizacoes else {})

    return {
        "email": u.get("primaryEmail", ""),
        "nome": nome.get("fullName") or f"{nome.get('givenName', '')} {nome.get('familyName', '')}".strip(),
        "setor": org_principal.get("department") or "",
        "cargo": org_principal.get("title") or "",
        "unidade_organizacional": u.get("orgUnitPath", "/"),
        "suspenso": bool(u.get("suspended")),
        "admin": bool(u.get("isAdmin")),
    }


def listar_atribuicoes_de_licenca():
    """Busca, de uma vez, todas as atribuicoes de licenca do Workspace
    (qualquer SKU) via Enterprise License Manager API. A propria API ja
    devolve o nome amigavel de cada SKU (skuName), entao nao precisa mapear
    id -> nome na mao.

    Diferente da Directory API (que aceita o atalho "my_customer"), a
    Licensing API exige o dominio primario de verdade em customerId - por
    isso usamos GOOGLE_WORKSPACE_DOMAIN aqui, e nao "my_customer".
    """
    service = obter_service_licensing()
    dominio = os.getenv("GOOGLE_WORKSPACE_DOMAIN", "").strip()
    if not dominio:
        raise GoogleAdminConfigError(
            "GOOGLE_WORKSPACE_DOMAIN não configurado — necessário para consultar licenças."
        )

    atribuicoes = []
    page_token = None
    paginas = 0

    while True:
        parametros = {"productId": PRODUTO_WORKSPACE, "customerId": dominio, "maxResults": 100}
        if page_token:
            parametros["pageToken"] = page_token
        resposta = service.licenseAssignments().listForProduct(**parametros).execute()

        for item in resposta.get("items", []):
            atribuicoes.append({
                "email": item.get("userId", ""),
                "sku_id": item.get("skuId", ""),
                "sku_nome": item.get("skuName", item.get("skuId", "")),
            })

        page_token = resposta.get("nextPageToken")
        paginas += 1
        if not page_token or paginas >= LIMITE_PAGINAS_SEGURANCA:
            break

    return atribuicoes


def mapa_licenca_por_usuario():
    """email -> {sku_id, sku_nome} - para mostrar a licenca de um usuario
    especifico na aba Geral do card de detalhes, sem precisar de uma chamada
    por usuario (usa o mesmo bulk fetch de listar_atribuicoes_de_licenca)."""
    return {a["email"].lower(): a for a in listar_atribuicoes_de_licenca() if a.get("email")}


def _total_configurado_manualmente(sku_id):
    """Le GOOGLE_LICENCAS_TOTAL do .env, formato 'skuId:total,skuId:total'.
    Usado quando a Reseller API nao estiver disponivel (assinatura nao e
    gerenciada por revenda) - ver README para como preencher."""
    bruto = os.getenv("GOOGLE_LICENCAS_TOTAL", "").strip()
    for par in bruto.split(","):
        par = par.strip()
        if ":" not in par:
            continue
        sid, total = par.split(":", 1)
        if sid.strip() == sku_id:
            try:
                return int(total.strip())
            except ValueError:
                return None
    return None


def _total_via_reseller(sku_id):
    """Tenta a Reseller API para o total contratado. So funciona se a
    assinatura da organizacao for gerenciada por um revendedor - caso
    contrario a API retorna erro (403/404) e a funcao devolve None em vez de
    propagar a excecao, para o chamador cair no valor manual."""
    dominio = os.getenv("GOOGLE_WORKSPACE_DOMAIN", "").strip()
    if not dominio:
        return None
    try:
        service = obter_service_reseller()
        resposta = service.subscriptions().list(customerId=dominio).execute()
        for assinatura in resposta.get("subscriptions", []):
            if assinatura.get("skuId") == sku_id:
                seats = assinatura.get("seats", {})
                total = seats.get("licensedNumberOfSeats") or seats.get("numberOfSeats")
                if total is not None:
                    return int(total)
    except Exception:
        return None
    return None


def resumo_licencas():
    """Agrupa as atribuicoes por SKU (em uso, via API) e tenta descobrir o
    total contratado (Reseller API, com fallback para GOOGLE_LICENCAS_TOTAL
    no .env). 'livre' fica None quando o total nao e conhecido por nenhum
    dos dois caminhos - mostrar como 'desconhecido', nunca inventar numero."""
    atribuicoes = listar_atribuicoes_de_licenca()

    por_sku = {}
    for a in atribuicoes:
        sid = a["sku_id"]
        if sid not in por_sku:
            por_sku[sid] = {"sku_id": sid, "sku_nome": a["sku_nome"], "em_uso": 0}
        por_sku[sid]["em_uso"] += 1

    resumo = []
    origem_total = {}
    for sid, dados in por_sku.items():
        total = _total_via_reseller(sid)
        origem = "reseller" if total is not None else None
        if total is None:
            total = _total_configurado_manualmente(sid)
            origem = "manual" if total is not None else None

        livre = (total - dados["em_uso"]) if total is not None else None
        resumo.append({
            "sku_id": sid,
            "sku_nome": dados["sku_nome"],
            "em_uso": dados["em_uso"],
            "total": total,
            "livre": livre,
            "origem_total": origem,
        })

    resumo.sort(key=lambda r: r["sku_nome"])
    return resumo


def listar_usuarios_da_licenca(sku_id):
    """Emails de quem tem uma SKU especifica atribuida - para o botao
    'listar colaboradores' de cada licenca na aba Licencas."""
    return sorted(a["email"] for a in listar_atribuicoes_de_licenca() if a["sku_id"] == sku_id)


def obter_licenca_do_usuario(email):
    """Licenca atual de um usuario especifico (ou None se nao tiver
    nenhuma), para a aba Geral do card de detalhes."""
    mapa = mapa_licenca_por_usuario()
    return mapa.get((email or "").lower())


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
