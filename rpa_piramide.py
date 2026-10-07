import sys

from painel.piramide import (
    PiramideConfigError,
    buscar_usuario_por_email,
    definir_ativo,
)

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
    usuario = buscar_usuario_por_email(email_usuario)
    if not usuario:
        return NAO_ENCONTRADO

    logins = usuario.get("logins") or []
    if len(logins) > 1 and not ativar:
        ativos = [u for u in logins if u["ativo"]]
        if not ativos:
            return JA_NO_ESTADO_DESEJADO
        if len(ativos) == 1:
            usuario = ativos[0]
            logins = [usuario]
    if len(logins) > 1:
        nomes = ", ".join(f"{u['login']} ({'ativo' if u['ativo'] else 'inativo'})" for u in logins)
        print(f"[PIRAMIDE] E-mail {email_usuario} está em mais de um login ({nomes}). "
              "Não vou alterar sem saber qual é o certo — faça pela tela do Pirâmide.", file=sys.stderr)
        return ERRO

    if usuario["ativo"] == ativar:
        return JA_NO_ESTADO_DESEJADO

    ok, mensagem = definir_ativo(usuario["login"], ativar, operador="automacao")
    if not ok:
        print(f"[PIRAMIDE] {mensagem}", file=sys.stderr)
        return ERRO
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
        usuario = buscar_usuario_por_email(email_usuario)
    except Exception as e:
        return ERRO, str(e)

    if not usuario:
        return NAO_ENCONTRADO, None

    logins = usuario.get("logins") or []
    if len(logins) > 1:
        return ERRO, "E-mail em mais de um login: " + ", ".join(
            f"{u['login']} ({'ativo' if u['ativo'] else 'inativo'})" for u in logins)

    return ("ativo" if usuario["ativo"] else "inativo"), usuario["login"]


def ativar_usuario_piramide(email_usuario):
    return executar_piramide_automatico(email_usuario, acao='ativar')


def desativar_usuario_piramide(email_usuario):
    return executar_piramide_automatico(email_usuario, acao='desativar')


if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()

    if len(sys.argv) > 1:
        email = sys.argv[1]
    else:
        print("USO: python rpa_piramide.py <email_usuario> [ativar|desativar]")
        sys.exit(1)

    acao = sys.argv[2].lower() if len(sys.argv) > 2 else 'desativar'
    resultado = executar_piramide_automatico(email, acao)
    sys.exit(resultado)
