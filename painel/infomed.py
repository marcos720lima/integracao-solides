import os

import oracledb

_thick_mode_iniciado = False

PERFIS_CONHECIDOS = {
    1: "Suporte",
    5000: "Email",
    5001: "Funcionário",
    6000: "SMS",
    10001: "Cliente",
    10002: "Transportador",
    10003: "Administrador",
    100000: "Infomed",
    100500: "Segurança e Desempenho",
    100816: "Email",
    110000: "Analisador de Dados",
    400000: "Funções Específicas",
    500001: "Atendimento - Especifico",
    500002: "Administração de Contratos",
    500003: "Autorizações Automáticas",
    500004: "Atendimento - AUDITOR",
    500005: "Autorizações Completas e Cadas",
    500006: "Vendas",
    500007: "Cópia do Perfil 500000",
    500008: "Administração de Contra. e Pre",
    500009: "Financeiro de Recebimento",
    500010: "Financeiro de Pagamento",
    500011: "Financeiro de Recebim e Pagame",
    500012: "Produção Médica Digitação",
    500013: "Produção Medica Auditoria",
    500014: "Produção Médica",
    500015: "Contabilidade",
    500016: "Call center",
    500017: "Financeiro",
    500018: "Atendimento",
    500019: "Cadastro",
    620000: "Consultas Necessárias a Vendas",
    700000: "Relatórios Diversos",
    800000: "Teste Cadastro",
    900000: "Comissões",
    900001: "Cópia do Perfil 900000",
    900002: "Aplicações Desenvolvidas",
    900004: "Prod-Medica Loc Básico",
    900005: "Prod-Medica Loc Avanç.",
    900006: "Prod-Medica Loc/Inter - Avanç.",
    900007: "Cópia do Perfil 500002",
    900008: "Cópia do Perfil 900007",
    900010: "Finan Recebimento Entrega",
    900011: "ANS / REEMBOLSO",
    900012: "LOCALIDADES",
    900013: "TSJ",
    900014: "FINANCEIRO - CONTAS A PAGAR",
    900015: "FINANCEIRO - TESOURARIA",
    900016: "FINANCEIRO - CONTAS A RECEBER",
    900017: "Aplicativo TI",
    900018: "Financeiro Unimed",
    900019: "Aplicativo Unimed",
    900020: "COORD FIN CONTAS A PAGAR",
}


class InfomedConfigError(Exception):
    pass


def _garantir_modo_thick():
    global _thick_mode_iniciado
    if _thick_mode_iniciado:
        return

    diretorio_cliente = os.getenv("INFOMED_ORACLE_CLIENT_DIR", "").strip()
    if diretorio_cliente:
        oracledb.init_oracle_client(lib_dir=diretorio_cliente)
    _thick_mode_iniciado = True


def _conexao():
    _garantir_modo_thick()

    dsn_pronto = os.getenv("INFOMED_DB_DSN", "").strip()
    host = os.getenv("INFOMED_DB_HOST", "").strip()
    porta = os.getenv("INFOMED_DB_PORT", "1521").strip()
    servico = os.getenv("INFOMED_DB_SERVICE", "").strip()
    usuario = os.getenv("INFOMED_DB_USER", "").strip()
    senha = os.getenv("INFOMED_DB_PASSWORD", "").strip()
    schema = os.getenv("INFOMED_DB_SCHEMA", "API").strip()

    if not usuario or not senha:
        raise InfomedConfigError("INFOMED_DB_USER / INFOMED_DB_PASSWORD não definidos no .env.")

    if dsn_pronto:
        dsn = dsn_pronto
    elif host and servico:
        dsn = f"{host}:{porta}/{servico}"
    else:
        raise InfomedConfigError(
            "Configure INFOMED_DB_DSN (ex: ORA_NOVA) ou INFOMED_DB_HOST + INFOMED_DB_SERVICE no .env."
        )

    diretorio_tns = os.getenv("INFOMED_TNS_ADMIN", "").strip()
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
                SELECT usu_codigo, usu_nome, usu_email, usu_ativo
                FROM {schema}.api_usuarios
                WHERE UPPER(usu_codigo) LIKE :termo
                   OR UPPER(usu_nome) LIKE :termo
                   OR UPPER(usu_email) LIKE :termo
                ORDER BY usu_nome
                FETCH FIRST :limite ROWS ONLY
                """,
                termo=termo_busca, limite=limite,
            )
            linhas = cursor.fetchall()

    return [
        {
            "codigo": codigo,
            "nome": nome,
            "email": email,
            "ativo": ativo == "S",
        }
        for codigo, nome, email, ativo in linhas
    ]


def _buscar_perfis(cursor, schema, codigo):
    try:
        cursor.execute(
            f"""
            SELECT p.per_codigo, p.per_desc, pu.peu_ativo
            FROM {schema}.api_perfis_usuario pu
            JOIN {schema}.api_perfis p ON p.per_codigo = pu.peu_per_codigo
            WHERE pu.peu_usu_codigo = :codigo
            ORDER BY p.per_desc
            """,
            codigo=codigo,
        )
        linhas = cursor.fetchall()
        return [{"codigo": cod, "nome": desc, "ativo": ativo == "S"} for cod, desc, ativo in linhas]
    except oracledb.DatabaseError:
        cursor.execute(
            f"""
            SELECT peu_per_codigo, peu_ativo
            FROM {schema}.api_perfis_usuario
            WHERE peu_usu_codigo = :codigo
            ORDER BY peu_per_codigo
            """,
            codigo=codigo,
        )
        linhas = cursor.fetchall()
        return [
            {"codigo": cod, "nome": PERFIS_CONHECIDOS.get(int(cod)), "ativo": ativo == "S"}
            for cod, ativo in linhas
        ]


def obter_usuario(codigo):
    conexao, schema = _conexao()

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT usu_codigo, usu_nome, usu_email, usu_ativo,
                       usu_expiracao_senha, usu_tentativas_login, usu_preferencias
                FROM {schema}.api_usuarios
                WHERE usu_codigo = :codigo
                """,
                codigo=codigo,
            )
            linha = cursor.fetchone()

            if not linha:
                return None

            perfis = _buscar_perfis(cursor, schema, codigo)

    codigo, nome, email, ativo, expiracao_senha, tentativas_login, preferencias = linha
    return {
        "codigo": codigo,
        "nome": nome,
        "email": email,
        "ativo": ativo == "S",
        "dias_expiracao_senha": expiracao_senha,
        "tentativas_login": tentativas_login,
        "salvar_preferencias": bool(preferencias) if preferencias is not None else None,
        "perfis": perfis,
    }


def alterar_perfil(codigo, per_codigo, ativo):
    conexao, schema = _conexao()
    novo_valor = "S" if ativo else "N"

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {schema}.api_usuarios WHERE usu_codigo = :codigo",
                codigo=codigo,
            )
            if cursor.fetchone()[0] != 1:
                return False, f"Esperava achar exatamente 1 usuário com código {codigo}, não vou arriscar atualizar."

            cursor.execute(
                f"""
                SELECT COUNT(*) FROM {schema}.api_perfis_usuario
                WHERE peu_usu_codigo = :codigo AND peu_per_codigo = :per_codigo
                """,
                codigo=codigo, per_codigo=per_codigo,
            )
            ja_vinculado = cursor.fetchone()[0] > 0

            if ja_vinculado:
                cursor.execute(
                    f"""
                    UPDATE {schema}.api_perfis_usuario
                    SET peu_ativo = :novo_valor
                    WHERE peu_usu_codigo = :codigo AND peu_per_codigo = :per_codigo
                    """,
                    novo_valor=novo_valor, codigo=codigo, per_codigo=per_codigo,
                )
                mensagem = "Perfil ativado." if ativo else "Perfil desativado."
            else:
                cursor.execute(
                    f"""
                    INSERT INTO {schema}.api_perfis_usuario (peu_usu_codigo, peu_per_codigo, peu_ativo)
                    VALUES (:codigo, :per_codigo, :novo_valor)
                    """,
                    codigo=codigo, per_codigo=per_codigo, novo_valor=novo_valor,
                )
                mensagem = "Perfil adicionado."

            conexao.commit()

    return True, mensagem


def editar_dados(codigo, nome, email):
    conexao, schema = _conexao()

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {schema}.api_usuarios WHERE usu_codigo = :codigo",
                codigo=codigo,
            )
            if cursor.fetchone()[0] != 1:
                return False, f"Esperava achar exatamente 1 usuário com código {codigo}, não vou arriscar atualizar."

            cursor.execute(
                f"UPDATE {schema}.api_usuarios SET usu_nome = :nome, usu_email = :email WHERE usu_codigo = :codigo",
                nome=nome, email=email or None, codigo=codigo,
            )
            conexao.commit()

    return True, "Dados atualizados."


def definir_ativo(codigo, ativo):
    conexao, schema = _conexao()
    novo_valor = "S" if ativo else "N"

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {schema}.api_usuarios WHERE usu_codigo = :codigo",
                codigo=codigo,
            )
            if cursor.fetchone()[0] != 1:
                return False, f"Esperava achar exatamente 1 usuário com código {codigo}, não vou arriscar atualizar."

            cursor.execute(
                f"UPDATE {schema}.api_usuarios SET usu_ativo = :novo_valor WHERE usu_codigo = :codigo",
                novo_valor=novo_valor, codigo=codigo,
            )
            conexao.commit()

    return True, ("Usuário ativado." if ativo else "Usuário inativado.")


def corrigir_preferencias(codigo, dias_expiracao_senha, tentativas_login, salvar_preferencias):
    conexao, schema = _conexao()
    valor_preferencias = 1 if salvar_preferencias else 0

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {schema}.api_usuarios WHERE usu_codigo = :codigo",
                codigo=codigo,
            )
            if cursor.fetchone()[0] != 1:
                return False, f"Esperava achar exatamente 1 usuário com código {codigo}, não vou arriscar atualizar."

            cursor.execute(
                f"""
                UPDATE {schema}.api_usuarios
                SET usu_expiracao_senha = :dias, usu_tentativas_login = :tentativas, usu_preferencias = :prefs
                WHERE usu_codigo = :codigo
                """,
                dias=dias_expiracao_senha, tentativas=tentativas_login, prefs=valor_preferencias, codigo=codigo,
            )
            conexao.commit()

    return True, "Preferências atualizadas."
