import sys

from painel.infomed import InfomedConfigError, _conexao

SUCESSO = 0
ERRO = 1
JA_NO_ESTADO_DESEJADO = 2
NAO_ENCONTRADO = 3

ACOES_VALIDAS = {
    "bloquear": "desativar",
    "desativar": "desativar",
    "inativar": "desativar",
    "desbloquear": "ativar",
    "ativar": "ativar",
}


def _definir_ativo_com_preferencias(email_usuario, ativar):
    conexao, schema = _conexao()
    novo_valor_ativo = "S" if ativar else "N"

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT usu_codigo, usu_ativo, usu_expiracao_senha
                FROM {schema}.api_usuarios
                WHERE usu_email = :email
                """,
                email=email_usuario,
            )
            linha = cursor.fetchone()
            if not linha:
                return NAO_ENCONTRADO

            codigo, ativo_atual, expiracao_atual = linha

            if (ativo_atual == "S") == ativar:
                return JA_NO_ESTADO_DESEJADO

            if expiracao_atual is None:
                novo_dias = 60
            elif int(expiracao_atual) == 60:
                novo_dias = 59
            else:
                novo_dias = 60

            cursor.execute(
                f"""
                SELECT COUNT(*) FROM {schema}.api_usuarios WHERE usu_codigo = :codigo
                """,
                codigo=codigo,
            )
            if cursor.fetchone()[0] != 1:
                return ERRO

            cursor.execute(
                f"""
                UPDATE {schema}.api_usuarios
                SET usu_ativo = :ativo,
                    usu_expiracao_senha = :dias,
                    usu_tentativas_login = 3,
                    usu_preferencias = 1
                WHERE usu_codigo = :codigo
                """,
                ativo=novo_valor_ativo, dias=novo_dias, codigo=codigo,
            )
            conexao.commit()

    return SUCESSO


def executar_infomed_automatico(email_usuario, acao='desativar'):
    acao_normalizada = ACOES_VALIDAS.get((acao or '').lower())
    if acao_normalizada is None:
        print(f"[INFOMED] Ação inválida: {acao}", file=sys.stderr)
        return ERRO

    if not email_usuario:
        print("[INFOMED] Email do usuário não informado.", file=sys.stderr)
        return ERRO

    try:
        return _definir_ativo_com_preferencias(email_usuario, acao_normalizada == 'ativar')
    except InfomedConfigError as e:
        print(f"[INFOMED] {e}", file=sys.stderr)
        return ERRO
    except Exception as exc:
        print(f"[INFOMED] Falha: {exc}", file=sys.stderr)
        return ERRO


def consultar_status_infomed(email_usuario):
    if not email_usuario:
        return ERRO, None

    try:
        conexao, schema = _conexao()
        with conexao:
            with conexao.cursor() as cursor:
                cursor.execute(
                    f"SELECT usu_codigo, usu_ativo FROM {schema}.api_usuarios WHERE usu_email = :email",
                    email=email_usuario,
                )
                linha = cursor.fetchone()
    except Exception as e:
        return ERRO, str(e)

    if not linha:
        return NAO_ENCONTRADO, None

    codigo, ativo = linha
    return ("ativo" if ativo == "S" else "inativo"), codigo


def ativar_usuario_infomed(email_usuario):
    return executar_infomed_automatico(email_usuario, acao='ativar')


def desativar_usuario_infomed(email_usuario):
    return executar_infomed_automatico(email_usuario, acao='desativar')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        email = sys.argv[1]
    else:
        print("USO: python rpa_infomed.py <email_usuario> [ativar|desativar]")
        sys.exit(1)

    acao = sys.argv[2].lower() if len(sys.argv) > 2 else 'desativar'
    resultado = executar_infomed_automatico(email, acao)
    sys.exit(resultado)
