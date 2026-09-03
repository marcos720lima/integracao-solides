import os

import oracledb

_thick_mode_iniciado = False


class PiramideConfigError(Exception):
    pass


def _garantir_modo_thick():
    global _thick_mode_iniciado
    if _thick_mode_iniciado:
        return

    diretorio_cliente = os.getenv("PIRAMIDE_ORACLE_CLIENT_DIR", "").strip()
    if diretorio_cliente:
        try:
            oracledb.init_oracle_client(lib_dir=diretorio_cliente)
        except Exception:
            pass
    _thick_mode_iniciado = True


def _conexao():
    _garantir_modo_thick()

    dsn_pronto = os.getenv("PIRAMIDE_DB_DSN", "").strip()
    host = os.getenv("PIRAMIDE_DB_HOST", "").strip()
    porta = os.getenv("PIRAMIDE_DB_PORT", "1521").strip()
    servico = os.getenv("PIRAMIDE_DB_SERVICE", "").strip()
    usuario = os.getenv("PIRAMIDE_DB_USER", "").strip()
    senha = os.getenv("PIRAMIDE_DB_PASSWORD", "").strip()
    schema = os.getenv("PIRAMIDE_DB_SCHEMA", "PIRAMIDE").strip()

    if not usuario or not senha:
        raise PiramideConfigError("PIRAMIDE_DB_USER / PIRAMIDE_DB_PASSWORD não definidos no .env.")

    if dsn_pronto:
        dsn = dsn_pronto
    elif host and servico:
        dsn = f"{host}:{porta}/{servico}"
    else:
        raise PiramideConfigError(
            "Configure PIRAMIDE_DB_DSN (ex: PRDCLOUD) ou PIRAMIDE_DB_HOST + PIRAMIDE_DB_SERVICE no .env."
        )

    diretorio_tns = os.getenv("PIRAMIDE_TNS_ADMIN", "").strip()
    if diretorio_tns:
        conexao = oracledb.connect(user=usuario, password=senha, dsn=dsn, config_dir=diretorio_tns)
    else:
        conexao = oracledb.connect(user=usuario, password=senha, dsn=dsn)
    return conexao, schema


def buscar_usuarios(termo, limite=50):
    conexao, schema = _conexao()
    termo_busca = f"%{termo.upper()}%"

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT nom_usuario_login, nom_usuario, dsc_email, cod_situacao
                FROM {schema}.usuario
                WHERE UPPER(nom_usuario_login) LIKE :termo
                   OR UPPER(nom_usuario) LIKE :termo
                   OR UPPER(dsc_email) LIKE :termo
                ORDER BY nom_usuario
                FETCH FIRST :limite ROWS ONLY
                """,
                termo=termo_busca, limite=limite,
            )
            linhas = cursor.fetchall()

    return [
        {
            "login": login,
            "nome": nome,
            "email": email,
            "ativo": situacao == "A",
        }
        for login, nome, email, situacao in linhas
    ]


def obter_usuario(login):
    conexao, schema = _conexao()

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT nom_usuario_login, nom_usuario, dsc_email, cod_situacao,
                       cod_login_secundario, ind_usuario_mobile, cod_cargo, dat_ult_alteracao
                FROM {schema}.usuario
                WHERE nom_usuario_login = :login
                """,
                login=login,
            )
            linha = cursor.fetchone()

    if not linha:
        return None

    login, nome, email, situacao, login_secundario, mobile, cargo, ult_alteracao = linha
    return {
        "login": login,
        "nome": nome,
        "email": email,
        "ativo": situacao == "A",
        "login_secundario": login_secundario,
        "mobile": mobile == "S",
        "cargo": cargo,
        "ultima_alteracao": ult_alteracao.strftime("%d/%m/%Y %H:%M") if ult_alteracao else None,
    }


def buscar_usuario_por_email(email):
    conexao, schema = _conexao()

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                f"SELECT nom_usuario_login, cod_situacao FROM {schema}.usuario WHERE UPPER(dsc_email) = UPPER(:email)",
                email=email,
            )
            linha = cursor.fetchone()

    if not linha:
        return None
    login, situacao = linha
    return {"login": login, "ativo": situacao == "A"}


def definir_ativo(login, ativo):
    conexao, schema = _conexao()
    novo_valor = "A" if ativo else "I"

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {schema}.usuario WHERE nom_usuario_login = :login",
                login=login,
            )
            if cursor.fetchone()[0] != 1:
                return False, f"Esperava achar exatamente 1 usuário com login {login}, não vou arriscar atualizar."

            cursor.execute(
                f"""
                UPDATE {schema}.usuario
                SET cod_situacao = :novo_valor, dat_ult_alteracao = SYSDATE
                WHERE nom_usuario_login = :login
                """,
                novo_valor=novo_valor, login=login,
            )
            conexao.commit()

    return True, ("Usuário ativado." if ativo else "Usuário inativado.")


def editar_dados(login, nome, email):
    conexao, schema = _conexao()

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {schema}.usuario WHERE nom_usuario_login = :login",
                login=login,
            )
            if cursor.fetchone()[0] != 1:
                return False, f"Esperava achar exatamente 1 usuário com login {login}, não vou arriscar atualizar."

            cursor.execute(
                f"UPDATE {schema}.usuario SET nom_usuario = :nome, dsc_email = :email WHERE nom_usuario_login = :login",
                nome=nome, email=email or None, login=login,
            )
            conexao.commit()

    return True, "Dados atualizados."
