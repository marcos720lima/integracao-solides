import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

class PiramideConfigError(Exception):
    pass


from painel.piramide_api import PiramideAPI, PiramideAPIError, gerar_senha

_api_instancia = None
_api_lock = threading.RLock()

SEM_REGISTROS = "não há registros"
LIMITE_EMAIL_NA_LISTA = int(os.getenv("PIRAMIDE_API_EMAIL_NA_LISTA", "20"))

ORIGENS = [
    ("000", "TI"),
    ("001", "CONTABILIDADE"),
    ("002", "FINANCEIRO"),
    ("003", "HUOP"),
    ("004", "FOLHA"),
    ("005", "INFOMED"),
    ("006", "LOCALIDADES"),
    ("007", "ESTOQUE/COMPRAS"),
    ("999", "INTEGRACAO"),
]


def _api():
    global _api_instancia
    with _api_lock:
        if _api_instancia is None:
            try:
                _api_instancia = PiramideAPI()
            except PiramideAPIError as e:
                raise PiramideConfigError(str(e))
        return _api_instancia


def ambiente():
    try:
        return _api().ambiente
    except PiramideConfigError:
        return "API (não configurada)"


def _consultar(filtro, operacao="Consultar"):
    filtro = dict(filtro)
    if operacao == "Consultar":
        filtro.setdefault("IND_ORD_NOME", "S")
        filtro.setdefault("IND_PERMISSOES", "N")
    try:
        with _api_lock:
            resultado = _api().chamar("wsUSUARIO.asmx", operacao, oFiltro=filtro)
    except PiramideAPIError as e:
        if SEM_REGISTROS in str(e).lower():
            return []
        raise
    if not resultado:
        return []
    return resultado if isinstance(resultado, list) else [resultado]


def _texto(valor):
    valor = (valor or "").strip() if isinstance(valor, str) else valor
    return valor or None


def _mapear(reg):
    return {
        "login": reg.get("NOM_USUARIO_LOGIN"),
        "nome": reg.get("NOM_USUARIO"),
        "email": _texto(reg.get("DSC_EMAIL")),
        "ativo": reg.get("COD_SITUACAO") == "A",
        "login_secundario": _texto(reg.get("COD_LOGIN_SECUNDARIO")),
        "mobile": reg.get("IND_USUARIO_MOBILE") == "S",
        "cargo": _texto(reg.get("COD_CARGO")),
        "origem_codigo": _texto(reg.get("COD_UNID_ORIGEM")),
        "origem": _texto(reg.get("_DSC_UNID_ORIGEM")),
        "perfil_codigo": _texto(reg.get("COD_PERFIL")),
        "perfil": _texto(reg.get("_NOM_PERFIL")),
        "ultima_alteracao": _texto(reg.get("DAT_ULT_ALTERACAO")),
    }


def _existe_de_verdade(reg):
    # ConsultarUsuario devolve um registro "vazio" (só com o login) quando o usuário não existe
    return bool(reg) and any((reg.get(c) or "").strip() for c in ("NOM_USUARIO", "COD_SITUACAO", "COD_PERFIL"))


def _registro_por_login(login):
    login = (login or "").strip().upper()
    if not login:
        return None
    for reg in _consultar({"NOM_USUARIO_LOGIN": login}, "ConsultarUsuario"):
        if (reg.get("NOM_USUARIO_LOGIN") or "").upper() == login and _existe_de_verdade(reg):
            return reg
    return None


def _api_buscar_usuarios(termo, limite=50):
    termo = termo.strip()
    encontrados = {}

    def juntar(registros):
        for reg in registros:
            login = reg.get("NOM_USUARIO_LOGIN")
            if login and login not in encontrados:
                encontrados[login] = _mapear(reg)

    if "@" in termo:
        achado = _api_buscar_usuario_por_email(termo)
        for item in (achado or {}).get("logins", []):
            reg = _registro_por_login(item["login"])
            if reg:
                juntar([reg])
    else:
        reg = _registro_por_login(termo)
        if reg:
            juntar([reg])
        juntar(_consultar({"NOM_USUARIO_LIKE": f"%{termo.upper()}%"}))

    resultado = list(encontrados.values())[:limite]
    for usuario in resultado[:LIMITE_EMAIL_NA_LISTA]:
        if not usuario["email"]:
            try:
                completo = _registro_por_login(usuario["login"])
                if completo:
                    usuario["email"] = _texto(completo.get("DSC_EMAIL"))
            except Exception:
                pass
    return resultado


def _api_obter_usuario(login):
    reg = _registro_por_login(login)
    return _mapear(reg) if reg else None


def _api_buscar_usuario_por_email(email, permitir_incremental=True):
    email = (email or "").strip().lower()
    if not email:
        return None

    indice = _carregar_indice()
    if indice is None:
        iniciar_reconstrucao_em_segundo_plano()
        raise PiramideConfigError(
            "O índice de e-mails do Pirâmide ainda está sendo montado (leva alguns minutos). "
            "Tente de novo daqui a pouco."
        )

    logins = _mapa_emails(indice).get(email, [])
    if not logins and permitir_incremental and time.time() - indice.get("atualizado_em", 0) > INDICE_INCREMENTAL_MIN_SEGUNDOS:
        indice = atualizar_indice_incremental()
        logins = _mapa_emails(indice).get(email, [])

    encontrados = []
    for login in logins:
        reg = _registro_por_login(login)
        if not reg:
            _atualizar_indice(None, login)
            continue
        email_atual = (reg.get("DSC_EMAIL") or "").strip().lower()
        if email_atual != email:
            _atualizar_indice(email_atual, login)
            continue
        encontrados.append({"login": reg.get("NOM_USUARIO_LOGIN"), "ativo": reg.get("COD_SITUACAO") == "A"})

    if not encontrados:
        return None

    encontrados.sort(key=lambda u: (not u["ativo"], u["login"]))
    resultado = dict(encontrados[0])
    resultado["logins"] = encontrados
    return resultado


# ----------------------------------------------------------------------
# Índice e-mail -> login (a API não busca usuário por e-mail)
# ----------------------------------------------------------------------

INDICE_TTL_SEGUNDOS = float(os.getenv("PIRAMIDE_API_INDICE_HORAS", "24")) * 3600
INDICE_INCREMENTAL_MIN_SEGUNDOS = float(os.getenv("PIRAMIDE_API_INDICE_INCREMENTAL_MIN", "2")) * 60
INDICE_PARALELO = int(os.getenv("PIRAMIDE_API_INDICE_PARALELO", "6"))
_indice_lock = threading.RLock()
_reconstrucao = {"rodando": False, "inicio": None, "erro": None}


def _arquivo_indice():
    pasta = Path(os.getenv("PIRAMIDE_API_INDICE_DIR") or Path(__file__).resolve().parent.parent / "data")
    return pasta / f"piramide_emails_{_api().ambiente}.json"


def _carregar_indice():
    try:
        with _arquivo_indice().open(encoding="utf-8") as f:
            dados = json.load(f)
        if isinstance(dados.get("logins"), dict):
            return dados
    except (OSError, ValueError):
        pass
    return None


def _salvar_indice(indice):
    arquivo = _arquivo_indice()
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    indice["total_usuarios"] = len(indice["logins"])
    indice["total_emails"] = sum(1 for e in indice["logins"].values() if e)
    temporario = arquivo.with_suffix(".tmp")
    with temporario.open("w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False)
    os.replace(temporario, arquivo)


def _mapa_emails(indice):
    mapa = {}
    for login, email in indice["logins"].items():
        if email:
            mapa.setdefault(email, []).append(login)
    return mapa


def _listar_logins():
    return sorted({r.get("NOM_USUARIO_LOGIN") for r in _consultar({}) if r.get("NOM_USUARIO_LOGIN")})


def _buscar_emails(logins):
    api = _api()

    def email_do_login(login):
        try:
            r = api.chamar("wsUSUARIO.asmx", "ConsultarUsuario",
                           oFiltro={"NOM_USUARIO_LOGIN": login, "IND_PERMISSOES": "N"})
        except PiramideAPIError as e:
            if SEM_REGISTROS in str(e).lower():
                return login, ""
            return login, None
        for reg in (r if isinstance(r, list) else [r]):
            if isinstance(reg, dict) and reg.get("NOM_USUARIO_LOGIN") == login:
                return login, (reg.get("DSC_EMAIL") or "").strip().lower()
        return login, ""

    resultado = {}
    with ThreadPoolExecutor(max_workers=max(1, INDICE_PARALELO)) as executor:
        for login, email in executor.map(email_do_login, logins):
            if email is not None:
                resultado[login] = email
    return resultado


def reconstruir_indice_emails():
    with _indice_lock:
        inicio = time.time()
        logins = _listar_logins()
        emails = _buscar_emails(logins)
        anterior = _carregar_indice() or {"logins": {}}
        for login in logins:
            if login not in emails and login in anterior["logins"]:
                emails[login] = anterior["logins"][login]
        agora = time.time()
        indice = {
            "ambiente": _api().ambiente,
            "gerado_em": agora,
            "atualizado_em": agora,
            "duracao_segundos": round(agora - inicio, 1),
            "logins": emails,
        }
        _salvar_indice(indice)
        return indice


def atualizar_indice_incremental():
    with _indice_lock:
        indice = _carregar_indice()
        if indice is None:
            return reconstruir_indice_emails()
        logins = _listar_logins()
        atuais = set(logins)
        for login in list(indice["logins"]):
            if login not in atuais:
                del indice["logins"][login]
        novos = [l for l in logins if l not in indice["logins"]]
        if novos:
            indice["logins"].update(_buscar_emails(novos))
        indice["atualizado_em"] = time.time()
        _salvar_indice(indice)
        return indice


def _executar_reconstrucao():
    try:
        reconstruir_indice_emails()
        _reconstrucao["erro"] = None
    except Exception as e:
        _reconstrucao["erro"] = str(e)
    finally:
        _reconstrucao["rodando"] = False


def iniciar_reconstrucao_em_segundo_plano():
    with _indice_lock:
        if _reconstrucao["rodando"]:
            return False
        _reconstrucao.update(rodando=True, inicio=time.time(), erro=None)
    threading.Thread(target=_executar_reconstrucao, daemon=True).start()
    return True


def _atualizar_indice(email, login):
    if not login:
        return
    with _indice_lock:
        indice = _carregar_indice()
        if not indice:
            return
        if email is None:
            indice["logins"].pop(login, None)
        else:
            indice["logins"][login] = (email or "").strip().lower()
        _salvar_indice(indice)


def status_indice_emails(iniciar_se_vencido=False):
    indice = _carregar_indice()
    vencido = indice is None or time.time() - indice.get("gerado_em", 0) > INDICE_TTL_SEGUNDOS
    if vencido and iniciar_se_vencido:
        iniciar_reconstrucao_em_segundo_plano()
    status = {
        "existe": indice is not None,
        "rodando": _reconstrucao["rodando"],
        "erro": _reconstrucao["erro"],
    }
    if indice:
        status.update(
            total_usuarios=indice.get("total_usuarios"),
            total_emails=indice.get("total_emails"),
            duracao_segundos=indice.get("duracao_segundos"),
            gerado_em=datetime.fromtimestamp(indice["gerado_em"]).strftime("%d/%m/%Y %H:%M"),
            vencido=vencido,
        )
    return status


def _checar_escrita():
    try:
        _api()._checar_escrita()
    except PiramideAPIError as e:
        raise PiramideConfigError(str(e))


def _api_definir_ativo(login, ativo, operador="painel"):
    _checar_escrita()
    reg = _registro_por_login(login)
    if not reg:
        return False, f"Usuário {login} não encontrado no Pirâmide."

    atual = reg.get("COD_SITUACAO") == "A"
    if atual == ativo:
        return True, "Usuário já estava ativo." if ativo else "Usuário já estava inativo."

    api = _api()
    novo = "A" if ativo else "I"
    situacao_atual = reg.get("COD_SITUACAO")
    try:
        with _api_lock:
            # AtivaDesativa inverte o status: recebe a situação ATUAL, não a desejada.
            api.chamar("wsUSUARIO.asmx", "AtivaDesativa",
                       poUSUARIO={"NOM_USUARIO_LOGIN": reg["NOM_USUARIO_LOGIN"], "COD_SITUACAO": situacao_atual})
    except Exception as e:
        api.registrar(operador, "AtivaDesativa", login, "ERRO", str(e))
        raise

    conferido = _registro_por_login(login)
    if not conferido or (conferido.get("COD_SITUACAO") == "A") != ativo:
        situacao = conferido.get("COD_SITUACAO") if conferido else "?"
        api.registrar(operador, "AtivaDesativa", login, "ERRO", f"API respondeu ok mas situação ficou {situacao}")
        return False, f"A API respondeu, mas o status não mudou (situação atual: {situacao})."

    api.registrar(operador, "AtivaDesativa", login, "OK", novo)
    return True, "Usuário ativado." if ativo else "Usuário inativado."


def _api_editar_dados(login, nome, email, operador="painel"):
    return False, (
        "Pela API do Pirâmide não dá pra editar um usuário sem trocar a senha junto. "
        "Altere nome/e-mail direto no Pirâmide ou use 'Redefinir senha'."
    )


ARRAYS_USUARIO = {
    "oPIR_ID_USUARIO": "fcPIR_ID_USUARIO_dados",
    "oPIR_ID_FILIAL_USUARIO": "fcPIR_ID_FILIAL_USUARIO_dados",
    "oPIR_ID_CCUSTO_USUARIO": "fcPIR_ID_CCUSTO_USUARIO_dados",
    "oPIR_ID_APLICACAO_USUARIO": "fcPIR_ID_APLICACAO_USUARIO_dados",
    "oPIR_USUARIO_LAYOUTIMP": "fcPIR_USUARIO_LAYOUTIMP_dados",
    "Atributos": "fcAtributos",
}


def _registro_completo(login):
    login = (login or "").strip().upper()
    for reg in _consultar({"NOM_USUARIO_LOGIN": login, "IND_PERMISSOES": "S"}, "ConsultarUsuario"):
        if (reg.get("NOM_USUARIO_LOGIN") or "").upper() == login and _existe_de_verdade(reg):
            return reg
    return None


def _contar_vinculos(reg):
    return {campo: len(reg.get(campo) or []) for campo in ARRAYS_USUARIO}


def _montar_para_alterar(reg):
    dados = {
        k: v for k, v in reg.items()
        if not k.startswith("_") and not isinstance(v, list) and v not in (None, "")
        and "PWD" not in k.upper() and "PASSWORD" not in k.upper()
        and k not in ("DAT_ULT_ALTERACAO", "HTLASTTOKEN")
    }
    for campo, tipo in ARRAYS_USUARIO.items():
        itens = [
            {k: v for k, v in item.items() if not k.startswith("_") and v not in (None, "")}
            for item in (reg.get(campo) or []) if isinstance(item, dict)
        ]
        if itens:
            dados[campo] = {tipo: itens}
    return dados


def redefinir_senha(login, senha=None, operador="painel"):
    _checar_escrita()

    senha = (senha or "").strip()
    if senha:
        if len(senha) < 6 or len(senha) > 30 or " " in senha:
            return False, "A senha precisa ter de 6 a 30 caracteres, sem espaços.", None
    else:
        senha = gerar_senha(8)

    reg = _registro_completo(login)
    if not reg:
        return False, f"Usuário {login} não encontrado no Pirâmide.", None
    antes = _contar_vinculos(reg)

    dados = _montar_para_alterar(reg)
    dados["PIRAMIDE_PWD"] = senha

    api = _api()
    try:
        with _api_lock:
            api.chamar("wsUSUARIO.asmx", "Alterar", poUSUARIO=dados)
    except Exception as e:
        api.registrar(operador, "RedefinirSenha", login, "ERRO", str(e))
        raise

    depois_reg = _registro_completo(login)
    depois = _contar_vinculos(depois_reg) if depois_reg else {}
    perdidos = {c: (antes[c], depois.get(c, 0)) for c in antes if depois.get(c, 0) < antes[c]}
    if perdidos:
        api.registrar(operador, "RedefinirSenha", login, "ATENCAO", {"vinculos_perdidos": perdidos})
        detalhe = ", ".join(f"{c}: {a}→{d}" for c, (a, d) in perdidos.items())
        return True, (f"Senha redefinida, MAS alguns vínculos sumiram ({detalhe}). "
                      "Confira o usuário no Pirâmide."), {"senha": senha}

    api.registrar(operador, "RedefinirSenha", login, "OK", {"vinculos": antes})
    return True, "Senha redefinida.", {"senha": senha}


FILIAIS_PADRAO = [
    ("196", "UNIMED OESTE DO PARÁ (matriz)"),
    ("002", "PRONTO ATENDIMENTO"),
    ("003", "JURUTI"),
    ("004", "ALTAMIRA"),
    ("005", "ITAITUBA"),
    ("006", "AME"),
    ("007", "AIS"),
    ("008", "CTE"),
    ("009", "CMU"),
    ("010", "NOVO HUOP"),
    ("011", "CFU"),
]
EMPRESAS_EXTRAS = [("123", "OESTE ADMINISTRAÇÃO DE IMÓVEIS")]
_perfis_cache = {"quando": 0.0, "lista": None}


def empresas_disponiveis():
    return [(c, n, True) for c, n in filiais()] + [(c, n, False) for c, n in EMPRESAS_EXTRAS]


def listar_perfis():
    if _perfis_cache["lista"] is not None and time.time() - _perfis_cache["quando"] < 3600:
        return _perfis_cache["lista"]
    try:
        with _api_lock:
            r = _api().chamar("wsPERFIL.asmx", "Consultar", {})
        lista = sorted(
            {(str(p.get("COD_PERFIL")), (p.get("NOM_PERFIL") or "").strip())
             for p in (r if isinstance(r, list) else [r]) if isinstance(p, dict) and p.get("COD_PERFIL")},
            key=lambda x: x[1],
        )
    except Exception:
        lista = []
    _perfis_cache.update(quando=time.time(), lista=lista)
    return lista


def empresas_do_usuario(login):
    try:
        with _api_lock:
            r = _api().chamar("wsUSUARIO_EMPRESA.asmx", "Consultar", {"USUARIO_LOGIN": login})
    except PiramideAPIError as e:
        if SEM_REGISTROS in str(e).lower():
            return []
        raise
    return sorted(x.get("EMPRESA") for x in (r if isinstance(r, list) else [r]) if isinstance(x, dict))


MATRICULA_TESTE_A_PARTIR_DE = int(os.getenv("PIRAMIDE_MATRICULA_IGNORAR_A_PARTIR_DE", "9000"))


def filiais():
    texto = os.getenv("PIRAMIDE_FILIAIS", "").strip()
    if not texto:
        return list(FILIAIS_PADRAO)
    lista = []
    for parte in texto.split(";"):
        if "=" in parte:
            codigo, nome = parte.split("=", 1)
            lista.append((codigo.strip(), nome.strip()))
    return lista or list(FILIAIS_PADRAO)


def _filial_valida(filial):
    return filial in {codigo for codigo, _ in filiais()}


def _colaboradores_brutos(filtro):
    try:
        with _api_lock:
            r = _api().chamar("wsCOLABORADOR.asmx", "Consultar", oFiltro=filtro)
    except PiramideAPIError as e:
        if SEM_REGISTROS in str(e).lower():
            return []
        raise
    if not r:
        return []
    return [c for c in (r if isinstance(r, list) else [r]) if isinstance(c, dict)]


def proxima_matricula(filial):
    if not _filial_valida(filial):
        raise PiramideConfigError(f"Filial {filial} desconhecida.")
    maior = 0
    tamanho = 6
    for c in _colaboradores_brutos({}):
        if c.get("COD_FILIAL") != filial:
            continue
        mat = (c.get("COD_MATRICULA") or "").strip()
        if mat.isdigit() and int(mat) < MATRICULA_TESTE_A_PARTIR_DE:
            maior = max(maior, int(mat))
            tamanho = max(tamanho, len(mat))
    return str(maior + 1).zfill(tamanho)


def _colaborador_por_matricula(filial, matricula, nome=None):
    # ConsultarColaboradorPessoa não devolve o código do colaborador; usa o Consultar e filtra aqui
    tentativas = []
    if nome:
        tentativas.append({"NOME_PESSOA__LIKE": f"%{nome.strip().upper()}%"})
    tentativas.append({"COD_MATRICULA__MAIORIGUAL": matricula, "COD_MATRICULA__MENORIGUAL": matricula})
    tentativas.append({})
    for filtro in tentativas:
        try:
            lista = _colaboradores_brutos(filtro)
        except PiramideAPIError:
            continue
        for c in lista:
            if c.get("COD_FILIAL") == filial and (c.get("COD_MATRICULA") or "").strip() == matricula \
                    and c.get("COD_COLABORADOR"):
                return c
        if "NOME_PESSOA__LIKE" not in filtro:
            return None
    return None


def criar_colaborador(nome, filial, matricula=None, operador="painel"):
    _checar_escrita()
    if not _filial_valida(filial):
        raise PiramideConfigError(f"Filial {filial} desconhecida.")
    matricula = (matricula or "").strip() or proxima_matricula(filial)
    if not matricula.isdigit():
        raise PiramideConfigError("A matrícula precisa ter só números.")
    if _colaborador_por_matricula(filial, matricula):
        raise PiramideConfigError(f"Já existe colaborador com a matrícula {matricula} na filial {filial}.")

    colaborador = {
        "COD_FILIAL": filial, "COD_EMPRESA": _api().empresa, "COD_MATRICULA": matricula,
        "NOME_PESSOA": nome.strip().upper(), "COD_TIPO_COLABOR": "01", "COD_SITUACAO_COLAB": "999",
        "SITUACAO_ATIVA": "S", "COD_CARGO": "06", "COD_FUNCAO": "01",
        "COD_ORIGEM": "161", "VAL_LIMITE_AUTVG": "0",
    }
    api = _api()
    try:
        with _api_lock:
            api.chamar("wsCOLABORADOR.asmx", "Incluir", poCOLABORADOR=colaborador)
    except Exception as e:
        api.registrar(operador, "IncluirColaborador", nome, "ERRO", str(e))
        raise

    criado = _colaborador_por_matricula(filial, matricula, nome)
    if not criado:
        api.registrar(operador, "IncluirColaborador", nome, "ERRO", "não apareceu na consulta")
        raise PiramideConfigError("O colaborador foi enviado, mas não apareceu na consulta. Confira no Pirâmide.")
    api.registrar(operador, "IncluirColaborador", nome, "OK",
                  {"codigo": criado["COD_COLABORADOR"], "filial": filial, "matricula": matricula})
    return {"codigo": criado["COD_COLABORADOR"], "matricula": matricula, "filial": filial}


def _incluir_com_nova_tentativa(usuario, login, operador):
    # o servidor da API às vezes devolve OutOfMemoryException; espera e tenta mais uma vez
    for tentativa in range(2):
        try:
            with _api_lock:
                _api().incluir_usuario(usuario, operador=operador)
            return
        except Exception as e:
            if tentativa == 0 and "outofmemory" in str(e).lower().replace(" ", ""):
                time.sleep(5)
                if _registro_por_login(login):
                    return
                continue
            raise


def criar_usuario(login, nome, email, cod_perfil, cod_unid_origem, cod_cargo,
                  filial=None, cod_colaborador=None, matricula=None, empresas=None, senha=None,
                  operador="painel"):
    _checar_escrita()

    login = (login or "").strip().upper()
    nome = (nome or "").strip()
    email = (email or "").strip()
    filial = (filial or "").strip()
    cod_colaborador = (cod_colaborador or "").strip()
    if not login or not nome or not email:
        return False, "Login, nome e e-mail são obrigatórios.", None
    if not filial or not _filial_valida(filial):
        return False, "Escolha a filial da pessoa.", None
    if len(login) > 30 or not login.replace("_", "").isalnum():
        return False, "Login inválido: use só letras, números ou _ (até 30 caracteres).", None
    senha = (senha or "").strip()
    if senha and (len(senha) < 6 or len(senha) > 30 or " " in senha):
        return False, "A senha precisa ter de 6 a 30 caracteres, sem espaços.", None
    if _registro_por_login(login):
        return False, f"Já existe usuário com o login {login}.", None

    colaborador_criado = None
    if not cod_colaborador:
        colaborador_criado = criar_colaborador(nome, filial, matricula, operador=operador)
        cod_colaborador = colaborador_criado["codigo"]

    senha_piramide = senha or gerar_senha(8)
    senha_oracle = gerar_senha(20)
    usuario = PiramideAPI.montar_usuario(
        login=login, nome=nome, email=email,
        cod_perfil=cod_perfil, cod_unid_origem=cod_unid_origem, cod_cargo=cod_cargo,
        senha_piramide=senha_piramide, senha_oracle=senha_oracle,
    )
    usuario["oPIR_ID_FILIAL_USUARIO"] = {"fcPIR_ID_FILIAL_USUARIO_dados": [{
        "COD_USUARIO_LOGIN": login, "COD_TIPO_ID_USUARIO": "003",
        "COD_FILIAL_ID": filial, "COD_CADASTRO_ID": cod_colaborador,
    }]}

    try:
        _incluir_com_nova_tentativa(usuario, login, operador)
    except Exception as e:
        if colaborador_criado:
            raise PiramideConfigError(
                f"O colaborador {cod_colaborador} (matrícula {colaborador_criado['matricula']}) foi criado, "
                f"mas a criação do usuário falhou: {e}. Tente de novo escolhendo esse colaborador na busca."
            )
        raise

    if not _registro_por_login(login):
        return False, "A API respondeu, mas o usuário não apareceu na consulta. Confira no Pirâmide.", None

    _atualizar_indice(email, login)

    etapas = [f"Acesso {login} criado no Administrador."]
    if colaborador_criado:
        etapas.append(f"Colaborador novo no Financeiro: {cod_colaborador}, matrícula {colaborador_criado['matricula']} (filial {filial}).")
    else:
        etapas.append(f"Ligado ao colaborador {cod_colaborador} do Financeiro (filial {filial}).")
    etapas.append("Identificação Filial: SOLICITANTE gravada.")

    empresas = [e for e in (empresas or []) if e]
    aviso_empresas = None
    if empresas:
        try:
            with _api_lock:
                _api().incluir_empresas_usuario(login, empresas, operador=operador)
        except Exception as e:
            aviso_empresas = f"não consegui gravar as empresas ({e})"
        if not aviso_empresas:
            gravadas = empresas_do_usuario(login)
            faltando = [e for e in empresas if e not in gravadas]
            if faltando:
                aviso_empresas = f"estas empresas não apareceram: {', '.join(faltando)}"
        if aviso_empresas:
            etapas.append(f"ATENÇÃO — Empresas: {aviso_empresas}. Marque na mão no Pirâmide (Usuário > Empresas).")
        else:
            etapas.append(f"Empresas liberadas: {', '.join(empresas)}.")
    else:
        etapas.append("Nenhuma empresa marcada — libere no Pirâmide (Usuário > Empresas).")

    return True, " ".join(etapas), {"login": login, "senha_piramide": senha_piramide,
                                    "colaborador": cod_colaborador, "filial": filial,
                                    "etapas": etapas, "aviso": bool(aviso_empresas) or not empresas}


def consultar_colaboradores(termo, filial=None, limite=30):
    termo = (termo or "").strip().upper()
    if not termo:
        return []
    lista = _colaboradores_brutos({"NOME_PESSOA__LIKE": f"%{termo}%"})
    if filial:
        lista = [c for c in lista if c.get("COD_FILIAL") == filial]
    return [
        {
            "codigo": c.get("COD_COLABORADOR"),
            "matricula": c.get("COD_MATRICULA"),
            "nome": (c.get("NOME_PESSOA") or "").strip(),
            "filial": c.get("COD_FILIAL"),
            "cargo": c.get("COD_CARGO"),
            "cargo_desc": c.get("_DSC_CARGO"),
            "situacao": c.get("DSC_SITUACAO_COLAB") or c.get("COD_SITUACAO_COLAB"),
        }
        for c in lista[:limite]
    ]


# ======================================================================
# Funções públicas
# ======================================================================

def buscar_usuarios(termo, limite=50):
    return _api_buscar_usuarios(termo, limite)


def obter_usuario(login):
    return _api_obter_usuario(login)


def buscar_usuario_por_email(email):
    return _api_buscar_usuario_por_email(email)


def definir_ativo(login, ativo, operador="painel"):
    return _api_definir_ativo(login, ativo, operador)


def editar_dados(login, nome, email, operador="painel"):
    return _api_editar_dados(login, nome, email, operador)
