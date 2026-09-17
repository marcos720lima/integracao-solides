import os

SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.user",
    "https://www.googleapis.com/auth/admin.directory.group",
    "https://www.googleapis.com/auth/admin.directory.group.member",
    "https://www.googleapis.com/auth/admin.directory.orgunit.readonly",
]


class GoogleAdminConfigError(Exception):
    pass


def _is_enabled() -> bool:
    return os.getenv("GOOGLE_ADMIN_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def obter_service_admin():
    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    delegated_admin = os.getenv("GOOGLE_DELEGATED_ADMIN", "").strip()

    if not service_account_file:
        raise GoogleAdminConfigError("GOOGLE_SERVICE_ACCOUNT_FILE não configurado")
    if not os.path.exists(service_account_file):
        raise GoogleAdminConfigError(f"JSON não encontrado: {service_account_file}")
    if not delegated_admin:
        raise GoogleAdminConfigError("GOOGLE_DELEGATED_ADMIN não configurado")

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
    creds = creds.with_subject(delegated_admin)
    return build("admin", "directory_v1", credentials=creds, cache_discovery=False)


def inativar_email_google_workspace(email: str | None) -> dict:
    """
    Suspende usuário no Google Workspace.
    Retorna dict padronizado com status:
      - sucesso
      - skipped
      - nao_encontrado
      - erro
    """
    nome_sistema = "Google Workspace"

    if not _is_enabled():
        return {"sistema": nome_sistema, "status": "skipped", "motivo": "Integração Google desabilitada"}

    if not email:
        return {"sistema": nome_sistema, "status": "skipped", "motivo": "Email do usuário não informado"}

    email = email.strip().lower()
    delegated_admin = os.getenv("GOOGLE_DELEGATED_ADMIN", "").strip().lower()
    allowed_domain = os.getenv("GOOGLE_WORKSPACE_DOMAIN", "").strip().lower()

    if delegated_admin and email == delegated_admin:
        return {"sistema": nome_sistema, "status": "skipped", "motivo": "Email do usuário é o admin delegado"}

    if allowed_domain and not email.endswith(f"@{allowed_domain}"):
        return {"sistema": nome_sistema, "status": "skipped", "motivo": "Email fora do domínio configurado"}

    try:
        from googleapiclient.errors import HttpError
    except Exception as exc:
        return {"sistema": nome_sistema, "status": "erro", "erro": f"Dependências Google ausentes: {exc}"}

    try:
        service = obter_service_admin()
    except GoogleAdminConfigError as exc:
        return {"sistema": nome_sistema, "status": "erro", "erro": str(exc)}
    except Exception as exc:
        return {"sistema": nome_sistema, "status": "erro", "erro": f"Dependências Google ausentes: {exc}"}

    # Antes de suspender, remove o usuario de todos os grupos de email que ele
    # participa. Import local para evitar import circular (google_workspace.py
    # importa deste modulo no topo do arquivo).
    grupos_removidos = 0
    grupos_total = 0
    grupos_status = "sem_grupos"
    try:
        from painel.google_workspace import remover_de_todos_os_grupos
        resultados_grupos = remover_de_todos_os_grupos(email)
        grupos_total = len(resultados_grupos)
        grupos_removidos = sum(1 for r in resultados_grupos if r["ok"])
        falhas = [r for r in resultados_grupos if not r["ok"]]

        if grupos_total == 0:
            grupos_status = "sem_grupos"
        elif not falhas:
            grupos_status = "sucesso"
        elif grupos_removidos > 0:
            grupos_status = "parcial"
        else:
            grupos_status = "erro"

        if falhas:
            print(f"[Google] Aviso: falha ao remover {email} de {len(falhas)} grupo(s): "
                  f"{[f['mensagem'] for f in falhas]}")
    except Exception as exc:
        grupos_status = "erro"
        print(f"[Google] Aviso: não foi possível remover grupos de {email} antes da suspensão: {exc}")

    try:
        service.users().patch(userKey=email, body={"suspended": True}).execute()
        return {
            "sistema": nome_sistema, "status": "sucesso",
            "grupos_removidos": grupos_removidos, "grupos_total": grupos_total,
            "grupos_status": grupos_status,
        }
    except HttpError as exc:
        status_code = getattr(getattr(exc, "resp", None), "status", None)
        if status_code == 404:
            return {"sistema": nome_sistema, "status": "nao_encontrado", "erro": "Usuário não encontrado no Google"}
        return {"sistema": nome_sistema, "status": "erro", "erro": str(exc)}
    except Exception as exc:
        return {"sistema": nome_sistema, "status": "erro", "erro": str(exc)}
