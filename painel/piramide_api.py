"""Cliente da API Pirâmide 360 (MV Procenge).

- Autenticar (wsSystem.asmx) é chamado em JSON.
- wsUSUARIO / wsCOLABORADOR são SOAP: o envelope é montado pelo zeep a partir do WSDL,
  então os nomes dos parâmetros vêm do próprio serviço.
"""
import json
import logging
import os
import secrets
import string
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
from xml.sax.saxutils import escape as _xml_escape
import xml.etree.ElementTree as ET
from zeep import Client, Settings
from zeep.transports import Transport

log = logging.getLogger(__name__)

URL_HOMOLOG = "http://192.168.0.5/Piramide360Service/"
HOST_PRODUCAO = "144.22.234.218"

TOKEN_VALIDADE = 1800
MARGEM_RENOVACAO = 120

LOG_CRIACAO = Path(os.getenv("PIRAMIDE_API_LOG", "logs/piramide_api.log"))


class PiramideAPIError(Exception):
    pass


def gerar_senha(tamanho=8):
    letras = string.ascii_letters
    alfabeto = letras + string.digits
    return secrets.choice(letras) + "".join(secrets.choice(alfabeto) for _ in range(tamanho - 1))


class PiramideAPI:
    def __init__(self, base_url=None, login=None, senha=None, versao=None, empresa=None, timeout=30):
        self.base_url = (base_url or os.getenv("PIRAMIDE_API_URL", URL_HOMOLOG)).rstrip("/") + "/"
        self.login = login or os.getenv("PIRAMIDE_API_LOGIN")
        self.senha = senha or os.getenv("PIRAMIDE_API_SENHA")
        self.versao = versao or os.getenv("PIRAMIDE_API_VERSAO", "Versão: 1.00.88")
        self.empresa = empresa or os.getenv("PIRAMIDE_API_EMPRESA", "196")
        self.timeout = timeout

        if not self.login or not self.senha:
            raise PiramideAPIError("Defina PIRAMIDE_API_LOGIN e PIRAMIDE_API_SENHA no .env")

        self._token = None
        self._token_obtido_em = 0.0
        self.ultima_resposta_auth = None
        self._clientes_soap = {}

        self._session = requests.Session()
        self._auth_lock = threading.RLock()

    @property
    def em_producao(self):
        return HOST_PRODUCAO in self.base_url

    @property
    def ambiente(self):
        return "PRODUCAO" if self.em_producao else "HOMOLOGACAO"

    def _checar_escrita(self):
        if self.em_producao and os.getenv("PIRAMIDE_API_PERMITIR_ESCRITA_PRODUCAO", "N").upper() != "S":
            raise PiramideAPIError(
                "Escrita em PRODUÇÃO bloqueada. Para liberar, defina "
                "PIRAMIDE_API_PERMITIR_ESCRITA_PRODUCAO=S no .env (só depois de validar em homologação)."
            )

    @staticmethod
    def _decodificar(valor):
        if isinstance(valor, str):
            try:
                return json.loads(valor)
            except ValueError:
                return valor
        return valor

    @staticmethod
    def _conteudo(resp, operacao):
        if isinstance(resp, dict) and "status" in resp:
            status = resp.get("status") or {}
            tipo = str(status.get("sTipo", "")).lower()
            # algumas operações (ex.: wsUSUARIO_EMPRESA.Incluir) gravam e devolvem sTipo vazio, sem mensagens
            if tipo == "" and not status.get("mensagens"):
                return resp.get("conteudo")
            if tipo != "success":
                msgs = "; ".join(
                    " ".join(filter(None, [m.get("sMensagem"), m.get("sDetalhe"), m.get("sSolucao")]))
                    for m in status.get("mensagens") or []
                ) or str(status)
                raise PiramideAPIError(f"{operacao}: {msgs}")
            return resp.get("conteudo")
        return resp

    def autenticar(self):
        url = f"{self.base_url}wsSystem.asmx/Autenticar"
        corpo = {"poAutenticar": {
            "LOGIN": self.login,
            "SENHA": self.senha,
            "APLICACAO": "Piramide360",
            "VERSAO": self.versao,
        }}
        r = self._session.post(url, json=corpo, timeout=self.timeout,
                               headers={"Content-Type": "application/json; charset=utf-8"})
        if r.status_code != 200:
            raise PiramideAPIError(f"Autenticar HTTP {r.status_code}: {r.text[:500]}")

        resp = self._decodificar(r.json().get("d"))
        self.ultima_resposta_auth = resp

        conteudo = self._conteudo(resp, "Autenticar")
        token = conteudo.get("TOKEN") if isinstance(conteudo, dict) else None
        if not token:
            raise PiramideAPIError(f"Token não encontrado na resposta: {resp}")

        self._token = token
        self._token_obtido_em = time.time()
        log.info("Pirâmide API: autenticado em %s (%s)", self.base_url, self.ambiente)
        return resp

    @property
    def token(self):
        with self._auth_lock:
            idade = time.time() - self._token_obtido_em
            if not self._token or idade > TOKEN_VALIDADE - MARGEM_RENOVACAO:
                self.autenticar()
            return self._token

    def _cliente(self, servico):
        with self._auth_lock:
            return self._cliente_sem_lock(servico)

    def _cliente_sem_lock(self, servico):
        if servico not in self._clientes_soap:
            wsdl = f"{self.base_url}{servico}?WSDL"
            transporte = Transport(session=self._session, timeout=self.timeout)
            self._clientes_soap[servico] = Client(wsdl, transport=transporte,
                                                  settings=Settings(strict=False))
        return self._clientes_soap[servico]

    def _parametros(self, servico, operacao):
        cliente = self._cliente(servico)
        try:
            op = cliente.service._binding._operations[operacao]
        except KeyError:
            raise PiramideAPIError(f"Operação {operacao} não existe em {servico}")
        params = []
        for nome, elemento in op.input.body.type.elements:
            tipo = getattr(elemento.type, "name", None) or type(elemento.type).__name__
            params.append((nome, tipo))
        return params

    def descrever(self, servico, operacao):
        return [f"{nome}: {tipo}" for nome, tipo in self._parametros(servico, operacao)]

    def descrever_campos(self, servico, operacao):
        cliente = self._cliente(servico)
        op = cliente.service._binding._operations[operacao]
        saida = {}
        for nome, elemento in op.input.body.type.elements:
            campos = []
            for sub_nome, sub_el in getattr(elemento.type, "elements", []) or []:
                sub_tipo = getattr(sub_el.type, "name", None) or type(sub_el.type).__name__
                campos.append(f"{sub_nome}: {sub_tipo}")
            saida[nome] = campos
        return saida

    def _montar_argumentos(self, servico, operacao, principal=None, nomeados=None):
        nomeados = nomeados or {}
        argumentos = {}
        principal_usado = principal is None
        for nome, tipo in self._parametros(servico, operacao):
            n = nome.lower()
            if n == "cabecalho":
                argumentos[nome] = {"token": self.token, "empresa": self.empresa}
            elif "token" in n:
                argumentos[nome] = self.token
            elif "empresa" in n:
                argumentos[nome] = self.empresa
            elif nome in nomeados:
                argumentos[nome] = nomeados[nome]
            elif not principal_usado:
                if isinstance(principal, (dict, list)) and str(tipo).lower() == "string":
                    argumentos[nome] = json.dumps(principal, ensure_ascii=False)
                else:
                    argumentos[nome] = principal
                principal_usado = True
            else:
                raise PiramideAPIError(
                    f"{operacao}: não sei preencher o parâmetro '{nome}' ({tipo}). "
                    f"Assinatura: {self.descrever(servico, operacao)}"
                )
        return argumentos

    def chamar(self, servico, operacao, principal=None, **nomeados):
        token_usado = self._token
        try:
            return self._chamar_uma_vez(servico, operacao, principal, nomeados)
        except PiramideAPIError as e:
            if "token" not in str(e).lower():
                raise
            with self._auth_lock:
                if self._token == token_usado:
                    log.info("Pirâmide API: token recusado em %s (%s), autenticando de novo", operacao, e)
                    self._reiniciar_sessao()
            return self._chamar_uma_vez(servico, operacao, principal, nomeados)

    def _reiniciar_sessao(self):
        self._token = None
        self._token_obtido_em = 0.0
        self._clientes_soap = {}
        try:
            self._session.close()
        except Exception:
            pass
        self._session = requests.Session()

    def _chamar_uma_vez(self, servico, operacao, principal, nomeados):
        argumentos = self._montar_argumentos(servico, operacao, principal, nomeados)
        cliente = self._cliente(servico)
        resultado = getattr(cliente.service, operacao)(**argumentos)
        return self._conteudo(self._decodificar(resultado), operacao)

    def consultar_colaboradores(self, nome=None, matricula=None, somente_ativos=True):
        filtro = {}
        if nome:
            filtro["NOME_PESSOA__LIKE"] = f"%{nome.strip().upper()}%"
        if matricula:
            filtro["COD_MATRICULA__MAIORIGUAL"] = str(matricula)
            filtro["COD_MATRICULA__MENORIGUAL"] = str(matricula)
        if somente_ativos:
            filtro["IND_ATIVO"] = "S"
        return self.chamar("wsCOLABORADOR.asmx", "Consultar", oFiltro=filtro)

    def consultar_usuarios(self, termo, com_permissoes=False, curinga=True):
        termo = termo.strip().upper()
        filtro = {
            "NOM_USUARIO_LIKE": f"%{termo}%" if curinga else termo,
            "IND_ORD_NOME": "S",
            "IND_PERMISSOES": "S" if com_permissoes else "N",
        }
        return self.chamar("wsUSUARIO.asmx", "ConsultarUsuario", oFiltro=filtro)

    def existe_usuario_bd(self, login):
        return self.chamar("wsUSUARIO.asmx", "ExisteUsuarioBD",
                           poUSUARIO={"NOM_USUARIO_LOGIN": login.strip().upper()})

    @staticmethod
    def montar_usuario(login, nome, email, cod_perfil, cod_unid_origem, cod_cargo,
                       senha_piramide, senha_oracle,
                       filiais=None, centros_custo=None, aplicacoes=None):
        login = login.strip().upper()
        usuario = {
            "NOM_USUARIO_LOGIN": login,
            "NOM_USUARIO": nome.strip().upper(),
            "COD_CARGO": str(cod_cargo),
            "COD_PERFIL": str(cod_perfil),
            "COD_UNID_ORIGEM": str(cod_unid_origem),
            "COD_SITUACAO": "A",
            "PIRAMIDE_PWD": senha_piramide,
            "ORACLE_PWD": senha_oracle,
            "DSC_EMAIL": email.strip().lower(),
            "DSC_PATH_RELATORIO": r"C:\PIRAMIDE\RELATORIOS",
            "COD_LOGIN_SECUNDARIO": login,
            "IND_USUARIO_MOBILE": "N",
            "IND_CAD_USUARIO_SISTEMA": "S",
        }
        if filiais:
            usuario["oPIR_ID_FILIAL_USUARIO"] = filiais
        if centros_custo:
            usuario["oPIR_ID_CCUSTO_USUARIO"] = centros_custo
        if aplicacoes:
            usuario["oPIR_ID_APLICACAO_USUARIO"] = aplicacoes
        return usuario

    def incluir_usuario(self, usuario, operador="desconhecido"):
        self._checar_escrita()
        login = usuario.get("NOM_USUARIO_LOGIN")
        try:
            resultado = self.chamar("wsUSUARIO.asmx", "Incluir", usuario)
            self._registrar(operador, "Incluir", login, "OK", resultado)
            return resultado
        except Exception as e:
            self._registrar(operador, "Incluir", login, "ERRO", str(e))
            raise

    @staticmethod
    def _sem_senhas(valor):
        if isinstance(valor, dict):
            return {k: ("***" if any(x in k.upper() for x in ("PWD", "PASSWORD", "SENHA")) else PiramideAPI._sem_senhas(v))
                    for k, v in valor.items()}
        if isinstance(valor, list):
            return [PiramideAPI._sem_senhas(v) for v in valor]
        return valor

    def registrar(self, operador, acao, login, status, detalhe=""):
        self._registrar(operador, acao, login, status, detalhe)

    def _soap_bruto(self, servico, operacao, corpo_interno):
        def montar():
            return (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
                f'<soap:Body><{operacao} xmlns="Pir360">'
                f'<cabecalho><token>{_xml_escape(str(self.token))}</token>'
                f'<empresa>{_xml_escape(str(self.empresa))}</empresa></cabecalho>'
                f'{corpo_interno}</{operacao}></soap:Body></soap:Envelope>'
            )

        def enviar():
            r = self._session.post(
                f"{self.base_url}{servico}", data=montar().encode("utf-8"), timeout=self.timeout,
                headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"Pir360/{operacao}"'},
            )
            if r.status_code != 200:
                raise PiramideAPIError(f"{servico} {operacao} HTTP {r.status_code}: {r.text[:500]}")
            resultado = None
            for el in ET.fromstring(r.content).iter():
                if el.tag.endswith(f"{operacao}Result"):
                    resultado = el.text
                    break
            return self._conteudo(self._decodificar(resultado), operacao)

        token_usado = self._token
        try:
            return enviar()
        except PiramideAPIError as e:
            if "token" not in str(e).lower():
                raise
            with self._auth_lock:
                if self._token == token_usado:
                    self._reiniciar_sessao()
            return enviar()

    def incluir_empresas_usuario(self, login, empresas, ind_status=None, operador="desconhecido"):
        self._checar_escrita()
        itens = []
        for emp in empresas:
            item = (f"<USUARIO_LOGIN>{_xml_escape(login)}</USUARIO_LOGIN>"
                    f"<EMPRESA>{_xml_escape(str(emp))}</EMPRESA>")
            if ind_status:
                item += f"<IND_STATUS>{_xml_escape(ind_status)}</IND_STATUS>"
            itens.append(f"<fcUSUARIO_EMPRESA_dados>{item}</fcUSUARIO_EMPRESA_dados>")
        corpo = f"<poUSUARIO_EMPRESA>{''.join(itens)}</poUSUARIO_EMPRESA>"
        try:
            r = self._soap_bruto("wsUSUARIO_EMPRESA.asmx", "Incluir", corpo)
            self._registrar(operador, "IncluirEmpresas", login, "OK", {"empresas": list(empresas)})
            return r
        except Exception as e:
            self._registrar(operador, "IncluirEmpresas", login, "ERRO", str(e))
            raise

    def _registrar(self, operador, acao, login, status, detalhe):
        detalhe = self._sem_senhas(detalhe)
        LOG_CRIACAO.parent.mkdir(parents=True, exist_ok=True)
        linha = {
            "quando": datetime.now().isoformat(timespec="seconds"),
            "operador": operador,
            "acao": acao,
            "login": login,
            "ambiente": self.ambiente,
            "status": status,
            "detalhe": detalhe if isinstance(detalhe, (str, dict, list)) else str(detalhe),
        }
        with LOG_CRIACAO.open("a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")
