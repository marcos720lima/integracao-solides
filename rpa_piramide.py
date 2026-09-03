import sys

from painel.piramide import PiramideConfigError, _conexao

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


def _definir_ativo_por_email(email_usuario, ativar):
    conexao, schema = _conexao()
    novo_valor = "A" if ativar else "I"

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                f"SELECT nom_usuario_login, cod_situacao FROM {schema}.usuario WHERE UPPER(dsc_email) = UPPER(:email)",
                email=email_usuario,
            )
            linha = cursor.fetchone()
            if not linha:
                return NAO_ENCONTRADO

            login, situacao_atual = linha

            if (situacao_atual == "A") == ativar:
                return JA_NO_ESTADO_DESEJADO

            cursor.execute(
                f"SELECT COUNT(*) FROM {schema}.usuario WHERE nom_usuario_login = :login",
                login=login,
            )
            if cursor.fetchone()[0] != 1:
                return ERRO

            cursor.execute(
                f"""
                UPDATE {schema}.usuario
                SET cod_situacao = :novo_valor, dat_ult_alteracao = SYSDATE
                WHERE nom_usuario_login = :login
                """,
                novo_valor=novo_valor, login=login,
            )
            conexao.commit()

    return SUCESSO


def executar_piramide_automatico(email_usuario, acao='desativar'):
    acao_normalizada = ACOES_VALIDAS.get((acao or '').lower())
    if acao_normalizada is None:
        print(f"[PIRAMIDE] Ação inválida: {acao}", file=sys.stderr)
        return ERRO

    if not email_usuario:
        print("[PIRAMIDE] Email do usuário não informado.", file=sys.stderr)
        return ERRO

    try:
        return _definir_ativo_por_email(email_usuario, acao_normalizada == 'ativar')
    except PiramideConfigError as e:
        print(f"[PIRAMIDE] {e}", file=sys.stderr)
        return ERRO
    except Exception as exc:
        print(f"[PIRAMIDE] Falha: {exc}", file=sys.stderr)
        return ERRO


def consultar_status_piramide(email_usuario):
    if not email_usuario:
        return ERRO, None

    try:
        conexao, schema = _conexao()
        with conexao:
            with conexao.cursor() as cursor:
                cursor.execute(
                    f"SELECT nom_usuario_login, cod_situacao FROM {schema}.usuario WHERE UPPER(dsc_email) = UPPER(:email)",
                    email=email_usuario,
                )
                linha = cursor.fetchone()
    except Exception as e:
        return ERRO, str(e)

    if not linha:
        return NAO_ENCONTRADO, None

    login, situacao = linha
    return ("ativo" if situacao == "A" else "inativo"), login


def ativar_usuario_piramide(email_usuario):
    return executar_piramide_automatico(email_usuario, acao='ativar')


def desativar_usuario_piramide(email_usuario):
    return executar_piramide_automatico(email_usuario, acao='desativar')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        email = sys.argv[1]
    else:
        print("USO: python rpa_piramide.py <email_usuario> [ativar|desativar]")
        sys.exit(1)

    acao = sys.argv[2].lower() if len(sys.argv) > 2 else 'desativar'
    resultado = executar_piramide_automatico(email, acao)
    sys.exit(resultado)
