"""Cliente da API do GIU (Gestao Institucional Unimed) - giu-api v3.1.73.

A API expoe apenas 8 endpoints. NAO existe inativacao nem edicao de usuario:
essas operacoes continuam dependendo do RPA (rpa_giu.py).

Uso:
    from painel.giu_api import GiuClient
    giu = GiuClient()
    dados = giu.resumo_usuario("12345678901")
    res = giu.auditar(["cpf1", "cpf2"])

Linha de comando:
    python painel/giu_api.py                     # mostra a sessao da conta
    python painel/giu_api.py 12345678901         # consulta um login
    python painel/giu_api.py --auditar cpfs.txt  # audita uma lista
"""

import os
import sys
import time
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

AMBIENTES = {
    "hml": "https://giuapihml.unimed.coop.br",
    "prd": "https://giuapi.unimed.coop.br",
}

ID_UNIMED_OESTE_PARA = "196"

TIMEOUT = 30
MARGEM_RENOVACAO = 120  # renova o token 2 min antes de expirar


class GiuError(Exception):
    pass


class GiuClient:
    def __init__(self, usuario=None, senha=None, ambiente=None, id_unimed=None):
        self.usuario = usuario or os.getenv("GIU_CLIENT_ID") or os.getenv("GIU_USUARIO")
        self.senha = senha or os.getenv("GIU_CLIENT_SECRET") or os.getenv("GIU_SENHA")
        ambiente = (ambiente or os.getenv("GIU_AMBIENTE") or "hml").lower()
        self.id_unimed = str(
            id_unimed or os.getenv("GIU_ID_UNIMED") or ID_UNIMED_OESTE_PARA
        )

        if ambiente not in AMBIENTES:
            raise GiuError(f"Ambiente invalido: {ambiente}. Use 'hml' ou 'prd'.")
        if not self.usuario or not self.senha:
            raise GiuError("Credenciais do GIU nao configuradas no .env.")

        self.base_url = AMBIENTES[ambiente]
        self.ambiente = ambiente
        self._token = None
        self._csrf = None
        self._expira_em = 0
        self._token_id = None
        self._user_id = None
        self._sessao = requests.Session()

    # ------------------------------------------------------------------ auth

    def autenticar(self, forcar=False):
        if not forcar and self._token and time.time() < self._expira_em:
            return self._token

        resp = self._sessao.post(
            f"{self.base_url}/api/token",
            headers={"Content-type": "application/json"},
            json={
                "grant_type": "password",
                "username": self.usuario,
                "password": self.senha,
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            raise GiuError(
                f"Falha na autenticacao ({resp.status_code}): {resp.text[:400]}"
            )

        dados = resp.json()
        self._token = dados.get("access_token") or dados.get("acess_token")
        if not self._token:
            raise GiuError(f"Token nao veio na resposta: {list(dados.keys())}")

        self._csrf = resp.cookies.get("X-CSRF-TOKEN") or self._sessao.cookies.get(
            "X-CSRF-TOKEN"
        )
        expira = int(dados.get("expires_in") or 1800)
        self._expira_em = time.time() + expira - MARGEM_RENOVACAO
        self._token_id = dados.get("token_id")
        self._user_id = dados.get("user_id")
        return self._token

    def _headers(self):
        self.autenticar()
        h = {
            "Content-type": "application/json",
            "Authorization": f"Bearer {self._token}",
            "X-Unimed-App": self.id_unimed,
            "X-UNIMED-APP": self.id_unimed,  # o cadastro documenta em caixa alta
        }
        if self._csrf:
            h["Cookie"] = f"X-CSRF-TOKEN={self._csrf}"
        return h

    def _request(self, metodo, caminho, **kwargs):
        url = f"{self.base_url}{caminho}"
        resp = self._sessao.request(
            metodo, url, headers=self._headers(), timeout=TIMEOUT, **kwargs
        )
        if resp.status_code == 401:
            self.autenticar(forcar=True)
            resp = self._sessao.request(
                metodo, url, headers=self._headers(), timeout=TIMEOUT, **kwargs
            )
        return resp

    @staticmethod
    def _json_ou_none(resp):
        if not resp.text.strip():
            return None
        try:
            return resp.json()
        except ValueError:
            raise GiuError(f"Resposta nao-JSON ({resp.status_code}): {resp.text[:300]}")

    # -------------------------------------------------------------- consultas

    def obter_sessao(self):
        resp = self._request("GET", "/api/usuario/obtem-sessao")
        return self._json_ou_none(resp)

    def consultar_usuario_por_login(self, login):
        """GET /api/usuario-unimed/obtem-por-login -> lista de vinculos, ou None."""
        resp = self._request(
            "GET", "/api/usuario-unimed/obtem-por-login", params={"login": login}
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise GiuError(f"Consulta falhou ({resp.status_code}): {resp.text[:400]}")
        return self._json_ou_none(resp)

    def resumo_usuario(self, login):
        """Achata o retorno da consulta no que interessa para o painel."""
        vinculos = self.consultar_usuario_por_login(login)
        if not vinculos:
            return {"login": login, "encontrado": False}

        primeiro = vinculos[0]
        colab = primeiro.get("colaborador") or primeiro.get("pessoaJuridica") or {}
        doc = colab.get("documento") or {}

        tipo = colab.get("tipoColaborador")
        if isinstance(tipo, dict):
            tipo = tipo.get("nome")

        aplicacoes = []
        for v in vinculos:
            for app in v.get("aplicacoes") or []:
                papeis = [p.get("nome") for p in (app.get("papeisAplicacao") or [])]
                aplicacoes.append({"nome": app.get("nome"), "papeis": papeis})

        return {
            "login": login,
            "encontrado": True,
            "nome": colab.get("nome"),
            "email": colab.get("email"),
            "cpf": doc.get("numeroDocumento"),
            "telefone": colab.get("telefone"),
            "status": colab.get("status"),  # ATIVO / INATIVO / PENDENTE
            "ultimo_acesso": colab.get("ultimoAcesso"),
            "tipo": tipo,
            "unimed": (primeiro.get("unimed") or {}).get("nome"),
            "perfil": (primeiro.get("perfil") or {}).get("nome"),
            "aplicacoes": aplicacoes,
        }

    def auditar(self, logins, pausa=0.2, on_erro=None):
        """Consulta uma lista de logins e agrupa por situacao."""
        res = {
            "ATIVO": [], "INATIVO": [], "PENDENTE": [],
            "SEM_STATUS": [], "NAO_ENCONTRADO": [], "ERRO": [],
        }
        for login in logins:
            try:
                r = self.resumo_usuario(login)
            except GiuError as e:
                res["ERRO"].append({"login": login, "erro": str(e)})
                if on_erro:
                    on_erro(login, e)
                time.sleep(pausa)
                continue

            if not r["encontrado"]:
                res["NAO_ENCONTRADO"].append(r)
            elif r["status"] in res:
                res[r["status"]].append(r)
            else:
                res["SEM_STATUS"].append(r)
            time.sleep(pausa)
        return res

    # --------------------------------------------------------------- escritas

    def cadastrar_colaborador(self, dados_colaborador, papeis=None):
        """POST /api/cadastro-simultaneo/colaborador (pessoa fisica).

        dados_colaborador exige: nome, email, telefone (10-11 digitos, so numeros),
        dataNascimento, genero, senha, tipoColaborador.
        """
        resp = self._request(
            "POST",
            "/api/cadastro-simultaneo/colaborador",
            json={"dadosColaborador": dados_colaborador, "papeis": papeis or []},
        )
        if resp.status_code not in (200, 201):
            raise GiuError(f"Cadastro falhou ({resp.status_code}): {resp.text[:400]}")
        return True

    def cadastrar_pessoa_juridica(self, dados, papeis=None):
        resp = self._request(
            "POST",
            "/api/cadastro-simultaneo/pessoa-juridica",
            json={"dadosPessoaJuridica": dados, "papeis": papeis or []},
        )
        if resp.status_code not in (200, 201):
            raise GiuError(f"Cadastro falhou ({resp.status_code}): {resp.text[:400]}")
        return True

    # NOTA: inativacao e edicao de usuario NAO existem na giu-api v3.1.73.
    # O contrato so tem POST (criacao) e um unico PUT (aceite de termo de uso).
    # Essas operacoes seguem no rpa_giu.py ate a Unimed do Brasil expor endpoints.


# ------------------------------------------------------------------ execucao

def main():
    args = sys.argv[1:]
    giu = GiuClient()
    print(f"Ambiente: {giu.ambiente} | Unimed id={giu.id_unimed}\n")

    if args and args[0] == "--auditar":
        if len(args) < 2:
            print("Uso: python painel/giu_api.py --auditar caminho/cpfs.txt")
            return
        with open(args[1], encoding="utf-8") as f:
            logins = [l.strip() for l in f if l.strip()]
        print(f"Auditando {len(logins)} logins...\n")
        res = giu.auditar(logins)
        for grupo, itens in res.items():
            print(f"  {grupo:15} {len(itens)}")
        with open("giu_auditoria.json", "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2, ensure_ascii=False)
        print("\nDetalhe salvo em giu_auditoria.json")
        return

    if not args:
        print(json.dumps(giu.obter_sessao(), indent=2, ensure_ascii=False)[:2000])
        return

    print(json.dumps(giu.resumo_usuario(args[0]), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
