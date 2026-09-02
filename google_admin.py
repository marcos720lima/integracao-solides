import os

SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.user",
    "https://www.googleapis.com/auth/admin.directory.group.readonly",
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

    try:
        service.users().patch(userKey=email, body={"suspended": True}).execute()
        return {"sistema": nome_sistema, "status": "sucesso"}
    except HttpError as exc:
        status_code = getattr(getattr(exc, "resp", None), "status", None)
        if status_code == 404:
            return {"sistema": nome_sistema, "status": "nao_encontrado", "erro": "Usuário não encontrado no Google"}
        return {"sistema": nome_sistema, "status": "erro", "erro": str(exc)}
    except Exception as exc:
        return {"sistema": nome_sistema, "status": "erro", "erro": str(exc)}
