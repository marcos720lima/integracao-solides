"""Cliente da API oficial do NextQS (v1).

Documentacao: https://api-docs.nextqs.com/
Base: https://api.nextqs.com/v1/
Auth: Authorization: Bearer <token>  (gerado em Next Manager > API)
Limite: 4000 req/hora por organizacao.

A API cobre a CONSULTA (listar agents/usuarios). A alteracao de status
(ativar/inativar) continua pelo RPA (rpa_nextqs.py), pois nao foi confirmado
endpoint de escrita na documentacao.
"""

import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

NEXTQS_API_BASE = os.getenv("NEXTQS_API_BASE", "https://api.nextqs.com/v1").rstrip("/")
NEXTQS_API_TOKEN = os.getenv("NEXTQS_API_TOKEN", "").strip()
NEXTQS_SITE_ID = os.getenv("NEXTQS_SITE_ID", "").strip()


def _carregar_mapa_perfis():
    """Le NEXTQS_PERFIS do .env no formato 'id1=Agente,id2=Administrador'.

    A API do NextQS não expõe os nomes dos perfis (só profile_id), então o
    de-para id -> nome fica aqui. Descubra os IDs listando os agents e
    preencha o .env; sem isso, a tela mostra o próprio ID.
    """
    bruto = os.getenv("NEXTQS_PERFIS", "").strip()
    mapa = {}
    for par in bruto.split(","):
        par = par.strip()
        if "=" in par:
            pid, nome = par.split("=", 1)
            mapa[pid.strip()] = nome.strip()
    return mapa


NEXTQS_MAPA_PERFIS = _carregar_mapa_perfis()

TIMEOUT = 30


class NextQSError(Exception):
    pass


class NextQSConfigError(NextQSError):
    pass


class NextQSClient:
    def __init__(self, token=None, site_id=None, base=None):
        self.token = token or NEXTQS_API_TOKEN
        self.site_id = site_id or NEXTQS_SITE_ID
        self.base = (base or NEXTQS_API_BASE).rstrip("/")
        if not self.token:
            raise NextQSConfigError("NEXTQS_API_TOKEN não configurado no .env.")
        self._sessao = requests.Session()

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _get(self, caminho, **kwargs):
        url = f"{self.base}{caminho}"
        resp = self._sessao.get(url, headers=self._headers(), timeout=TIMEOUT, **kwargs)
        if resp.status_code == 401:
            raise NextQSError("Token inválido ou expirado (401).")
        if resp.status_code == 429:
            raise NextQSError("Limite de requisições excedido (429).")
        return resp

    # ------------------------------------------------------------ endpoints

    def checar_credenciais(self):
        """GET /organization/check — testa se o token é válido."""
        resp = self._get("/organization/check")
        return resp.status_code == 200

    def obter_assets_do_site(self, site_id=None):
        """GET /organization/assets/sites/:site_id

        Retorna os assets do site: queues, service desks, displays, agents e
        schedules. Os 'agents' são os usuários que interessam à tela.
        """
        sid = site_id or self.site_id
        if not sid:
            raise NextQSConfigError("NEXTQS_SITE_ID não configurado no .env.")
        resp = self._get(f"/organization/assets/sites/{sid}")
        if resp.status_code != 200:
            raise NextQSError(f"Falha ao obter assets ({resp.status_code}): {resp.text[:300]}")
        return resp.json()

    def buscar_usuario_por_email(self, email):
        """GET /organization/users/:email — retorna um agent, ou None.

        Campos: _id, name, surname, username (email), profile_id, sites_id.
        """
        if not email:
            return None
        resp = self._get(f"/organization/users/{email}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise NextQSError(f"Busca falhou ({resp.status_code}): {resp.text[:300]}")
        if not resp.text.strip():
            return None
        try:
            dados = resp.json()
        except ValueError:
            raise NextQSError(f"Resposta não-JSON: {resp.text[:300]}")
        if not dados:
            return None
        return _normalizar_agent(dados, NEXTQS_MAPA_PERFIS)


def _normalizar_agent(a, mapa_perfis=None):
    """Achata um agent no formato usado pela tela.

    Campos reais da API (confirmados):
      _id, name, surname, username (é o email/login), profile_id, sites_id.
    O perfil vem como ID; mapa_perfis (id -> nome) o traduz quando disponível.
    O status NÃO vem na API — é obtido pelo RPA (rpa_nextqs.py).
    """
    if not isinstance(a, dict):
        return {"raw": a}

    nome = " ".join(p for p in [a.get("name"), a.get("surname")] if p).strip()
    profile_id = a.get("profile_id")
    perfil = None
    if mapa_perfis and profile_id in mapa_perfis:
        perfil = mapa_perfis[profile_id]

    return {
        "id": a.get("_id"),
        "nome": nome or None,
        "email": a.get("username"),
        "profile_id": profile_id,
        "perfil": perfil,          # nome legível, se resolvido; senão None
        "sites_id": a.get("sites_id") or [],
    }


if __name__ == "__main__":
    import sys, json
    cli = NextQSClient()
    print("Credenciais OK:", cli.checar_credenciais())
    if len(sys.argv) > 1:
        print(json.dumps(cli.buscar_usuario_por_email(sys.argv[1]), indent=2, ensure_ascii=False))
    else:
        print("Passe um email para testar: python painel/nextqs_api.py fulano@dominio")
