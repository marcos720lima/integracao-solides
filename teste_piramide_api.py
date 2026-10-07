"""Teste do cliente Pirâmide 360 — rodar da pasta C:\\IntegracaoSolides com o venv ativo.

python teste_piramide_api.py auth
python teste_piramide_api.py descrever > operacoes_piramide.txt
python teste_piramide_api.py existe MATEUSLS
python teste_piramide_api.py colab MATEUS
python teste_piramide_api.py usuarios MATEUS > usuarios_mateus.txt
python teste_piramide_api.py campos > campos_piramide.txt
python teste_piramide_api.py sondar MATEUS > sondagem.txt
python teste_piramide_api.py email MATEUSLS > sondagem_email.txt
python teste_piramide_api.py ativadesativa MATEUSLS > sondagem_ativa.txt
python teste_piramide_api.py poremail mateus.sousa@unimedoestedopara.coop.br > sondagem_poremail.txt
python teste_piramide_api.py emailextra mateus.sousa@unimedoestedopara.coop.br > sondagem_emailextra.txt
python teste_piramide_api.py validatelogin mateus.sousa@unimedoestedopara.coop.br > sondagem_validate.txt
python teste_piramide_api.py indice mateus.sousa@unimedoestedopara.coop.br
python teste_piramide_api.py token > sondagem_token.txt
python teste_piramide_api.py estrutura LOGIN_COMPLETO "NOME DO COLABORADOR" > sondagem_estrutura.txt
python teste_piramide_api.py resetsenha TESTEAPI1
python teste_piramide_api.py colabteste "TESTE API COLABORADOR" 999901 > sondagem_colab.txt
python teste_piramide_api.py vincular TESTEAPI1 @CODIGO 196 > sondagem_vinculo.txt
python teste_piramide_api.py servicos > sondagem_servicos.txt
python teste_piramide_api.py empresas ELLENC > sondagem_empresas.txt
python teste_piramide_api.py incluirempresa TESTEAPI3 196 > sondagem_incluirempresa.txt
python teste_piramide_api.py excluircolab "TESTE API COLABORADOR"
python teste_piramide_api.py incluirvinculo TESTEAPI2 "TESTE API DOIS" seu.email@unimedoestedopara.coop.br @881 196 > sondagem_incluirvinculo.txt
python teste_piramide_api.py incluir TESTEAPI1 "TESTE API UM" teste.api1@unimedoestedopara.com.br
"""
import json
import sys

from dotenv import load_dotenv
load_dotenv()

from painel.piramide_api import PiramideAPI, gerar_senha


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    modo = sys.argv[1]
    api = PiramideAPI()
    print(f"URL: {api.base_url} | ambiente: {api.ambiente}")

    if modo == "auth":
        api.autenticar()
        print("OK, token:", str(api.token)[:20], "...")
        print("Resposta bruta:", api.ultima_resposta_auth)

    elif modo == "descrever":
        for servico in ("wsUSUARIO.asmx", "wsCOLABORADOR.asmx"):
            try:
                operacoes = sorted(api._cliente(servico).service._binding._operations)
            except Exception as e:
                print(f"\n{servico}: ERRO ao ler WSDL: {e}")
                continue
            for op in operacoes:
                print(f"\n{servico} -> {op}:")
                for p in api.descrever(servico, op):
                    print("   ", p)

    elif modo == "existe":
        print(api.existe_usuario_bd(sys.argv[2]))

    elif modo == "colab":
        resultado = api.consultar_colaboradores(nome=sys.argv[2])
        print(json.dumps(resultado, ensure_ascii=False, indent=2) if isinstance(resultado, (dict, list)) else resultado)

    elif modo == "usuarios":
        resultado = api.consultar_usuarios(sys.argv[2])
        print(json.dumps(resultado, ensure_ascii=False, indent=2) if isinstance(resultado, (dict, list)) else resultado)

    elif modo == "campos":
        alvos = [
            ("wsUSUARIO.asmx", "ConsultarUsuario"),
            ("wsUSUARIO.asmx", "Incluir"),
            ("wsUSUARIO.asmx", "AtivaDesativa"),
            ("wsCOLABORADOR.asmx", "Consultar"),
            ("wsCOLABORADOR.asmx", "Incluir"),
        ]
        for servico, op in alvos:
            print(f"\n===== {servico} -> {op} =====")
            for param, campos in api.descrever_campos(servico, op).items():
                print(f"  {param}:")
                for c in campos:
                    print("     ", c)

    elif modo == "sondar":
        termo = sys.argv[2].upper()
        tentativas = [termo, f"{termo}%", f"%{termo}%"]
        for op in ("ConsultarUsuario", "Consultar"):
            for valor in tentativas:
                filtro = {"NOM_USUARIO_LIKE": valor, "IND_ORD_NOME": "S", "IND_PERMISSOES": "N"}
                try:
                    r = api.chamar("wsUSUARIO.asmx", op, oFiltro=filtro)
                    qtd = len(r) if isinstance(r, list) else 1
                    print(f"[OK]   {op} NOM_USUARIO_LIKE='{valor}' -> {qtd} registro(s)")
                    amostra = r[0] if isinstance(r, list) and r else r
                    print(json.dumps(amostra, ensure_ascii=False, indent=2, default=str))
                except Exception as e:
                    print(f"[ERRO] {op} NOM_USUARIO_LIKE='{valor}' -> {e}")
        print("\n--- ExisteUsuarioBD ---")
        try:
            print(api.existe_usuario_bd(sys.argv[3] if len(sys.argv) > 3 else "MATEUSLS"))
        except Exception as e:
            print("ERRO:", e)

    elif modo == "email":
        login = sys.argv[2].upper()
        tentativas = [
            ("Consultar", {"NOM_USUARIO_LOGIN": login, "IND_PERMISSOES": "N"}),
            ("Consultar", {"NOM_USUARIO_LOGIN": login, "IND_PERMISSOES": "S"}),
            ("ConsultarUsuario", {"NOM_USUARIO_LOGIN": login}),
            ("ConsultarUsuario", {"NOM_USUARIO_LOGIN": login, "IND_PERMISSOES": "S"}),
            ("ConsultarVisibilidadeUsuario", {"NOM_USUARIO_LOGIN": login}),
            ("ConsultarUsuarioOrcamento", {"NOM_USUARIO_LOGIN": login}),
        ]
        for op, filtro in tentativas:
            print(f"\n===== {op} {filtro} =====")
            try:
                r = api.chamar("wsUSUARIO.asmx", op, oFiltro=filtro)
                lista = r if isinstance(r, list) else [r]
                print(f"{len(lista)} registro(s)")
                for reg in lista[:3]:
                    if isinstance(reg, dict):
                        print("  LOGIN:", reg.get("NOM_USUARIO_LOGIN"), "| EMAIL:", repr(reg.get("DSC_EMAIL")))
                        preenchidos = {k: v for k, v in reg.items() if v not in ("", None, [])
                                       and "PWD" not in k and "PASSWORD" not in k}
                        print("  campos preenchidos:", json.dumps(preenchidos, ensure_ascii=False, default=str)[:1500])
                    else:
                        print("  ", str(reg)[:500])
            except Exception as e:
                print("ERRO:", e)

    elif modo == "ativadesativa":
        if api.em_producao:
            print("PARADO: este teste só roda em homologação.")
            return
        login = sys.argv[2].upper()

        def ler():
            r = api.chamar("wsUSUARIO.asmx", "Consultar",
                           oFiltro={"NOM_USUARIO_LOGIN": login, "IND_PERMISSOES": "N"})
            for reg in (r if isinstance(r, list) else [r]):
                if isinstance(reg, dict) and reg.get("NOM_USUARIO_LOGIN") == login:
                    return reg
            return None

        def completo(reg, situacao):
            d = {k: v for k, v in reg.items()
                 if not k.startswith("_") and not isinstance(v, list) and v not in ("", None)
                 and "PWD" not in k and "PASSWORD" not in k
                 and k not in ("DAT_ULT_ALTERACAO", "HTLASTTOKEN")}
            d["COD_SITUACAO"] = situacao
            return d

        variantes = [
            ("A: login + situacao ATUAL", lambda reg, atual, novo: {"NOM_USUARIO_LOGIN": login, "COD_SITUACAO": atual}),
            ("B: so login", lambda reg, atual, novo: {"NOM_USUARIO_LOGIN": login}),
            ("C: cadastro completo + situacao NOVA", lambda reg, atual, novo: completo(reg, novo)),
            ("D: cadastro completo + situacao ATUAL", lambda reg, atual, novo: completo(reg, atual)),
        ]

        reg = ler()
        if not reg:
            print("Usuário não encontrado.")
            return
        inicial = reg["COD_SITUACAO"]
        print("Situação inicial:", inicial)

        funcionou = None
        for nome, montar in variantes:
            atual = reg["COD_SITUACAO"]
            novo = "I" if atual == "A" else "A"
            corpo = montar(reg, atual, novo)
            print(f"\n===== {nome} =====")
            print("enviado:", json.dumps(corpo, ensure_ascii=False))
            try:
                resp = api.chamar("wsUSUARIO.asmx", "AtivaDesativa", poUSUARIO=corpo)
                print("resposta:", json.dumps(resp, ensure_ascii=False, default=str)[:800])
            except Exception as e:
                print("ERRO:", e)
            reg = ler()
            print("situação depois:", reg["COD_SITUACAO"])
            if reg["COD_SITUACAO"] != atual:
                funcionou = (nome, montar)
                print(">>> MUDOU com a variante", nome)
                break

        if funcionou and reg["COD_SITUACAO"] != inicial:
            atual = reg["COD_SITUACAO"]
            novo = "I" if atual == "A" else "A"
            print("\n===== Voltando ao estado inicial com a mesma variante =====")
            try:
                api.chamar("wsUSUARIO.asmx", "AtivaDesativa", poUSUARIO=funcionou[1](reg, atual, novo))
            except Exception as e:
                print("ERRO ao voltar:", e)
            reg = ler()
            print("situação final:", reg["COD_SITUACAO"], "(inicial era", inicial + ")")
        elif not funcionou:
            print("\nNenhuma variante mudou a situação.")

    elif modo == "poremail":
        email = sys.argv[2].strip()
        for op in ("ConsultarUsuario", "Consultar"):
            for valor in (email, email.lower(), email.upper()):
                print(f"\n===== {op} DSC_EMAIL='{valor}' =====")
                try:
                    r = api.chamar("wsUSUARIO.asmx", op, oFiltro={"DSC_EMAIL": valor})
                    lista = r if isinstance(r, list) else [r]
                    print(f"{len(lista)} registro(s)")
                    for reg in lista[:5]:
                        print("  ", reg.get("NOM_USUARIO_LOGIN"), "|", repr(reg.get("DSC_EMAIL")))
                except Exception as e:
                    print("ERRO:", e)

    elif modo == "emailextra":
        email = sys.argv[2].strip()
        tentativas = [
            ("ConsultarUsuario", {}),
            ("ConsultarUsuario", {"IND_PERMISSOES": "N"}),
            ("ConsultarUsuario", {"NOM_USUARIO_LIKE": "%"}),
            ("ConsultarUsuario", {"NOM_USUARIO_LIKE": f"%{email.upper()}%"}),
            ("Consultar", {"NOM_USUARIO_LIKE": f"%{email.upper()}%"}),
            ("ConsultarUsuario", {"DSC_EMAIL": email, "NOM_USUARIO_LIKE": "%"}),
        ]
        for op, filtro in tentativas:
            print(f"\n===== {op} {filtro} =====")
            try:
                r = api.chamar("wsUSUARIO.asmx", op, oFiltro=filtro)
                lista = r if isinstance(r, list) else [r]
                com_email = [x for x in lista if isinstance(x, dict) and x.get("DSC_EMAIL")]
                achou = [x.get("NOM_USUARIO_LOGIN") for x in lista
                         if isinstance(x, dict) and (x.get("DSC_EMAIL") or "").lower() == email.lower()]
                print(f"{len(lista)} registro(s), {len(com_email)} com e-mail preenchido, login do e-mail procurado: {achou}")
                for reg in lista[:3]:
                    print("  ", reg.get("NOM_USUARIO_LOGIN"), "|", repr(reg.get("DSC_EMAIL")))
            except Exception as e:
                print("ERRO:", e)

    elif modo == "validatelogin":
        email = sys.argv[2].strip()
        tentativas = [
            {"DSC_EMAIL": email},
            {"NOM_USUARIO_LOGIN": "MATEUSLS"},
            {"NOM_USUARIO_LOGIN": "MATEUSLS", "DSC_EMAIL": email},
            {"NOM_USUARIO_LOGIN": "NAOEXISTE999"},
            {"NOM_USUARIO_LOGIN": "NAOEXISTE999", "DSC_EMAIL": email},
        ]
        for corpo in tentativas:
            print(f"\n===== ValidateLogin {corpo} =====")
            try:
                r = api.chamar("wsUSUARIO.asmx", "ValidateLogin", poUSUARIO=corpo)
                print("resposta:", json.dumps(r, ensure_ascii=False, default=str)[:1500])
            except Exception as e:
                print("ERRO:", e)

    elif modo == "indice":
        import painel.piramide as piramide
        piramide._api_instancia = api
        print("Montando índice de e-mails pela API (pode levar alguns minutos)...")
        indice = piramide.reconstruir_indice_emails()
        print(f"Usuários: {indice['total_usuarios']} | com e-mail: {indice['total_emails']} | "
              f"tempo: {indice['duracao_segundos']}s")
        repetidos = {e: ls for e, ls in piramide._mapa_emails(indice).items() if len(ls) > 1}
        print(f"E-mails usados em mais de um login: {len(repetidos)}")
        for e, ls in sorted(repetidos.items()):
            print(f"   {e}: {', '.join(ls)}")
        if len(sys.argv) > 2:
            print("Busca por e-mail:", piramide._api_buscar_usuario_por_email(sys.argv[2]))

    elif modo == "token":
        def consulta(cliente, rotulo):
            try:
                cliente._chamar_uma_vez("wsUSUARIO.asmx", "ConsultarUsuario", None,
                                        {"oFiltro": {"NOM_USUARIO_LOGIN": cliente.login, "IND_PERMISSOES": "N"}})
                print(f"   {rotulo}: OK")
            except Exception as e:
                print(f"   {rotulo}: ERRO -> {e}")

        a = api
        a.autenticar()
        token_a = a._token
        print("1) Cliente A autenticou. token A =", str(token_a)[:12], "...")
        consulta(a, "A consultando")

        b = PiramideAPI()
        b.autenticar()
        token_b = b._token
        print("2) Cliente B autenticou (mesmo login). token B =", str(token_b)[:12], "...",
              "| igual ao A?", token_a == token_b)
        consulta(b, "B consultando")
        consulta(a, "A consultando de novo (depois do B)")

        a._token = None
        a.autenticar()
        print("3) Cliente A autenticou de novo. token =", str(a._token)[:12], "...",
              "| igual ao antigo A?", a._token == token_a, "| igual ao B?", a._token == token_b)
        consulta(a, "A consultando com token novo")
        consulta(b, "B consultando (depois do A reautenticar)")

    elif modo == "estrutura":
        login = sys.argv[2].upper()
        nome_colab = sys.argv[3] if len(sys.argv) > 3 else None

        def mostrar(titulo, valor):
            print(f"\n===== {titulo} =====")
            texto = json.dumps(PiramideAPI._sem_senhas(valor), ensure_ascii=False, indent=2, default=str)
            print(texto[:20000])

        print("\n######## Campos das operações de senha ########")
        for op in ("MudarSenha", "ValidaSenha", "ValidatePassword"):
            try:
                for param, campos in api.descrever_campos("wsUSUARIO.asmx", op).items():
                    print(f"{op} -> {param}: {campos}")
            except Exception as e:
                print(f"{op}: ERRO {e}")

        print("\n######## Campos dos vínculos do usuário ########")
        try:
            cliente = api._cliente("wsUSUARIO.asmx")
            for tipo in ("fcPIR_ID_USUARIO_dados", "fcPIR_ID_FILIAL_USUARIO_dados",
                         "fcPIR_ID_CCUSTO_USUARIO_dados", "fcPIR_ID_APLICACAO_USUARIO_dados"):
                try:
                    t = cliente.get_type(f"{{Pir360}}{tipo}")
                    print(tipo, "->", [n for n, _ in t.elements])
                except Exception as e:
                    print(tipo, "-> ERRO", e)
        except Exception as e:
            print("ERRO:", e)

        try:
            r = api.chamar("wsUSUARIO.asmx", "ConsultarUsuario",
                           oFiltro={"NOM_USUARIO_LOGIN": login, "IND_PERMISSOES": "S"})
            mostrar(f"ConsultarUsuario {login} (com permissões)", r)
        except Exception as e:
            print(f"\nConsultarUsuario {login}: ERRO {e}")

        if nome_colab:
            for op in ("Consultar", "ConsultarColaboradorFilial", "ConsultarColaboradorPessoa"):
                filtro = {"NOME_PESSOA__LIKE": f"%{nome_colab.upper()}%", "LOAD_DEPTO": "S"}
                if op == "ConsultarColaboradorPessoa":
                    try:
                        print(f"\n{op} campos do filtro:", api.descrever_campos("wsCOLABORADOR.asmx", op))
                    except Exception as e:
                        print(op, "ERRO", e)
                    continue
                try:
                    r = api.chamar("wsCOLABORADOR.asmx", op, oFiltro=filtro)
                    lista = r if isinstance(r, list) else [r]
                    mostrar(f"wsCOLABORADOR.{op} '{nome_colab}' ({len(lista)} registro(s), mostrando 3)", lista[:3])
                except Exception as e:
                    print(f"\nwsCOLABORADOR.{op}: ERRO {e}")

    elif modo == "resetsenha":
        if api.em_producao:
            print("PARADO: este teste só roda em homologação.")
            return
        login = sys.argv[2].upper()
        if login in ("MARCOSL", api.login.upper()):
            print("PARADO: não teste no seu próprio login.")
            return
        r = api.chamar("wsUSUARIO.asmx", "ConsultarUsuario",
                       oFiltro={"NOM_USUARIO_LOGIN": login, "IND_PERMISSOES": "N"})
        reg = next((x for x in (r if isinstance(r, list) else [r])
                    if isinstance(x, dict) and x.get("NOM_USUARIO_LOGIN") == login), None)
        if not reg:
            print("Usuário não encontrado.")
            return
        dados = {k: v for k, v in reg.items()
                 if not k.startswith("_") and not isinstance(v, list) and v not in ("", None)
                 and "PWD" not in k.upper() and "PASSWORD" not in k.upper()
                 and k not in ("DAT_ULT_ALTERACAO", "HTLASTTOKEN")}
        nova = gerar_senha(8)
        dados["PIRAMIDE_PWD"] = nova
        print("Campos enviados (sem senha):", sorted(dados))
        try:
            resp = api.chamar("wsUSUARIO.asmx", "Alterar", poUSUARIO=dados)
            print("Resposta:", json.dumps(resp, ensure_ascii=False, default=str)[:800])
            print(f"\nNOVA SENHA DO PIRÂMIDE PARA {login}: {nova}")
            print("Entre no Pirâmide de homologação com ela pra confirmar.")
        except Exception as e:
            print("ERRO:", e)

    elif modo == "colabteste":
        if api.em_producao:
            print("PARADO: este teste só roda em homologação.")
            return
        nome, matricula = sys.argv[2].upper(), sys.argv[3]

        def consultar_nome():
            try:
                r = api.chamar("wsCOLABORADOR.asmx", "Consultar", oFiltro={"NOME_PESSOA__LIKE": f"%{nome}%"})
                return r if isinstance(r, list) else [r]
            except Exception as e:
                print("Consultar:", e)
                return []

        print("1) Matrícula livre na filial 196?")
        try:
            r = api.chamar("wsCOLABORADOR.asmx", "ConsultarColaboradorPessoa",
                           oFiltro={"COD_FILIAL": "196", "COD_MATRICULA": matricula})
            print("   JÁ EXISTE algo com essa matrícula:", json.dumps(r, ensure_ascii=False, default=str)[:600])
            print("   Escolha outra matrícula.")
            return
        except Exception as e:
            print("   livre (", e, ")")

        colaborador = {
            "COD_FILIAL": "196", "COD_EMPRESA": "196", "COD_MATRICULA": matricula,
            "NOME_PESSOA": nome, "COD_TIPO_COLABOR": "01", "COD_SITUACAO_COLAB": "999",
            "SITUACAO_ATIVA": "S", "COD_CARGO": "06", "COD_FUNCAO": "01",
            "COD_ORIGEM": "161", "VAL_LIMITE_AUTVG": "0",
        }
        print("\n2) wsCOLABORADOR.Incluir:", json.dumps(colaborador, ensure_ascii=False))
        try:
            resp = api.chamar("wsCOLABORADOR.asmx", "Incluir", poCOLABORADOR=colaborador)
            print("   resposta:", json.dumps(resp, ensure_ascii=False, default=str)[:1500])
        except Exception as e:
            print("   ERRO:", e)
            return

        achados = consultar_nome()
        print(f"\n3) Depois do Incluir: {len(achados)} registro(s)")
        for c in achados:
            print("  ", c.get("COD_COLABORADOR"), "| filial", c.get("COD_FILIAL"), "| mat", c.get("COD_MATRICULA"))
        if not achados:
            return

        base = {k: v for k, v in achados[0].items() if not k.startswith("_") and not isinstance(v, list) and v != ""}
        print("\n4) wsCOLABORADOR.ReplicarFiliais com", base.get("COD_COLABORADOR"))
        try:
            resp = api.chamar("wsCOLABORADOR.asmx", "ReplicarFiliais", poCOLABORADOR=base)
            print("   resposta:", json.dumps(resp, ensure_ascii=False, default=str)[:1500])
        except Exception as e:
            print("   ERRO:", e)

        achados = consultar_nome()
        print(f"\n5) Depois do ReplicarFiliais: {len(achados)} registro(s)")
        for c in achados:
            print("  ", c.get("COD_COLABORADOR"), "| filial", c.get("COD_FILIAL"), "| mat", c.get("COD_MATRICULA"))

    elif modo == "vincular":
        if api.em_producao:
            print("PARADO: este teste só roda em homologação.")
            return
        login, cod_colab, filial = sys.argv[2].upper(), sys.argv[3], sys.argv[4]
        if login in ("MARCOSL", api.login.upper()):
            print("PARADO: não teste no seu próprio login.")
            return

        def ler():
            r = api.chamar("wsUSUARIO.asmx", "ConsultarUsuario",
                           oFiltro={"NOM_USUARIO_LOGIN": login, "IND_PERMISSOES": "S"})
            return next((x for x in (r if isinstance(r, list) else [r])
                         if isinstance(x, dict) and x.get("NOM_USUARIO_LOGIN") == login), None)

        def base_sem_listas(reg):
            return {k: v for k, v in reg.items()
                    if not k.startswith("_") and not isinstance(v, list) and v not in ("", None)
                    and "PWD" not in k.upper() and "PASSWORD" not in k.upper()
                    and k not in ("DAT_ULT_ALTERACAO", "HTLASTTOKEN")}

        def limpar(item):
            return {k: v for k, v in item.items() if not k.startswith("_") and v not in ("", None)}

        reg = ler()
        if not reg:
            print("Usuário não encontrado.")
            return
        vinculos = [limpar(v) for v in reg.get("oPIR_ID_FILIAL_USUARIO") or []]
        print("Vínculos atuais:", vinculos)
        vinculos.append({"COD_USUARIO_LOGIN": login, "COD_TIPO_ID_USUARIO": "003",
                         "COD_FILIAL_ID": filial, "COD_CADASTRO_ID": cod_colab})

        dados = base_sem_listas(reg)
        dados["oPIR_ID_FILIAL_USUARIO"] = {"fcPIR_ID_FILIAL_USUARIO_dados": vinculos}
        print("\n1) Alterar com vínculo SOLICITANTE", cod_colab, "filial", filial)
        try:
            resp = api.chamar("wsUSUARIO.asmx", "Alterar", poUSUARIO=dados)
            print("   resposta:", json.dumps(resp, ensure_ascii=False, default=str)[:800])
        except Exception as e:
            print("   ERRO:", e)
            return
        reg = ler()
        print("   vínculos agora:", json.dumps(reg.get("oPIR_ID_FILIAL_USUARIO"), ensure_ascii=False)[:1500])

        print("\n2) Alterar SEM mandar vínculos (igual ao 'Editar dados' do painel) — os vínculos continuam?")
        try:
            api.chamar("wsUSUARIO.asmx", "Alterar", poUSUARIO=base_sem_listas(reg))
        except Exception as e:
            print("   ERRO:", e)
        reg = ler()
        qtd = len(reg.get("oPIR_ID_FILIAL_USUARIO") or [])
        print(f"   vínculos depois: {qtd}", "-> CONTINUAM" if qtd else "-> FORAM APAGADOS")

    elif modo == "incluirvinculo":
        if api.em_producao:
            print("PARADO: este teste só roda em homologação.")
            return
        login, nome, email, cod_colab, filial = sys.argv[2].upper(), sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6]
        senha_pir = gerar_senha(8)
        usuario = PiramideAPI.montar_usuario(
            login=login, nome=nome, email=email,
            cod_perfil="21", cod_unid_origem="000", cod_cargo="06",
            senha_piramide=senha_pir, senha_oracle=gerar_senha(20),
        )
        usuario["oPIR_ID_FILIAL_USUARIO"] = {"fcPIR_ID_FILIAL_USUARIO_dados": [{
            "COD_USUARIO_LOGIN": login, "COD_TIPO_ID_USUARIO": "003",
            "COD_FILIAL_ID": filial, "COD_CADASTRO_ID": cod_colab,
        }]}
        print(f"Incluindo {login} já ligado ao colaborador {cod_colab} (filial {filial}) como SOLICITANTE")
        try:
            resp = api.incluir_usuario(usuario, operador="teste_local")
            print("resposta:", json.dumps(resp, ensure_ascii=False, default=str)[:800])
        except Exception as e:
            print("ERRO:", e)
            return
        r = api.chamar("wsUSUARIO.asmx", "ConsultarUsuario",
                       oFiltro={"NOM_USUARIO_LOGIN": login, "IND_PERMISSOES": "S"})
        reg = next((x for x in (r if isinstance(r, list) else [r])
                    if isinstance(x, dict) and x.get("NOM_USUARIO_LOGIN") == login), {})
        print("Identificação Filial gravada:",
              json.dumps(reg.get("oPIR_ID_FILIAL_USUARIO"), ensure_ascii=False, indent=2))
        print(f"\nSenha do Pirâmide de {login}: {senha_pir}")

    elif modo == "excluircolab":
        if api.em_producao:
            print("PARADO: este teste só roda em homologação.")
            return
        nome = sys.argv[2].upper()
        if "TESTE" not in nome:
            print("PARADO: por segurança só apago colaborador com 'TESTE' no nome.")
            return
        try:
            r = api.chamar("wsCOLABORADOR.asmx", "Consultar", oFiltro={"NOME_PESSOA__LIKE": f"%{nome}%"})
        except Exception as e:
            print("Nada encontrado:", e)
            return
        lista = [c for c in (r if isinstance(r, list) else [r]) if (c.get("NOME_PESSOA") or "").upper() == nome]
        print(f"{len(lista)} colaborador(es) com o nome exato {nome}")
        for c in lista:
            base = {k: v for k, v in c.items() if not k.startswith("_") and not isinstance(v, list) and v != ""}
            try:
                api.chamar("wsCOLABORADOR.asmx", "Excluir", poCOLABORADOR=base)
                print("  apagado", c.get("COD_COLABORADOR"), "filial", c.get("COD_FILIAL"))
            except Exception as e:
                print("  ERRO", c.get("COD_COLABORADOR"), "filial", c.get("COD_FILIAL"), "->", e)

    elif modo == "servicos":
        nomes = [
            "wsUSUARIO_EMPRESA", "wsUSUARIOEMPRESA", "wsEMPRESA_USUARIO", "wsEMPRESAUSUARIO",
            "wsUSUARIO_FILIAL", "wsUSUARIOFILIAL", "wsEMPRESA", "wsFILIAL", "wsEMP_FILIAL",
            "wsPERFIL", "wsUSUARIO_PERFIL", "wsUSUARIOS", "wsPERMISSAO", "wsSystem",
            "wsCOLABORADOR", "wsUSUARIO",
        ]
        for nome in nomes:
            url = f"{api.base_url}{nome}.asmx"
            try:
                r = api._session.get(url, timeout=20)
                existe = r.status_code == 200 and "operations" in r.text.lower()
                ops = []
                if existe:
                    import re
                    ops = sorted(set(re.findall(r'\?op=([A-Za-z0-9_]+)', r.text)))
                print(f"{'EXISTE ' if existe else 'nao    '} {nome}.asmx  (HTTP {r.status_code})  {', '.join(ops)}")
            except Exception as e:
                print(f"ERRO    {nome}.asmx  {e}")

    elif modo == "empresas":
        login = sys.argv[2].upper()

        def mostrar(titulo, valor, limite=4000):
            print(f"\n===== {titulo} =====")
            print(json.dumps(PiramideAPI._sem_senhas(valor), ensure_ascii=False, indent=2, default=str)[:limite])

        alvos = [("wsUSUARIO_EMPRESA.asmx", op) for op in
                 ("Consultar", "ConsultarEmpresaUsuario", "ConsultarEmpresaOrigemDestino", "Incluir")]
        alvos += [("wsFILIAL.asmx", "Consultar"), ("wsPERFIL.asmx", "Consultar")]
        print("######## Campos ########")
        for servico, op in alvos:
            try:
                for param, campos in api.descrever_campos(servico, op).items():
                    print(f"{servico} {op} -> {param}: {campos}")
            except Exception as e:
                print(f"{servico} {op}: ERRO {e}")

        for op in ("ConsultarEmpresaUsuario", "Consultar"):
            for filtro in ({"USUARIO_LOGIN": login}, {"NOM_USUARIO_LOGIN": login}, {"COD_USUARIO_LOGIN": login}):
                try:
                    r = api.chamar("wsUSUARIO_EMPRESA.asmx", op, filtro)
                    mostrar(f"wsUSUARIO_EMPRESA.{op} {filtro}", r)
                    break
                except Exception as e:
                    print(f"\nwsUSUARIO_EMPRESA.{op} {filtro}: ERRO {e}")

        for servico in ("wsFILIAL.asmx", "wsPERFIL.asmx"):
            try:
                r = api.chamar(servico, "Consultar", {})
                lista = r if isinstance(r, list) else [r]
                mostrar(f"{servico} Consultar ({len(lista)} registro(s), mostrando 15)", lista[:15], 8000)
            except Exception as e:
                print(f"\n{servico} Consultar: ERRO {e}")

    elif modo == "incluirempresa":
        if api.em_producao:
            print("PARADO: este teste só roda em homologação.")
            return
        login = sys.argv[2].upper()
        empresas = sys.argv[3:] or ["196"]

        def atuais():
            try:
                r = api.chamar("wsUSUARIO_EMPRESA.asmx", "Consultar", {"USUARIO_LOGIN": login})
                return sorted(x.get("EMPRESA") for x in (r if isinstance(r, list) else [r]) if isinstance(x, dict))
            except Exception:
                return []

        print("Empresas antes:", atuais())
        for status in (None, "I", "N", "S", "A"):
            print(f"\n===== XML direto, IND_STATUS={status} =====")
            try:
                r = api.incluir_empresas_usuario(login, empresas, ind_status=status, operador="teste_local")
                print("   resposta:", json.dumps(r, ensure_ascii=False, default=str)[:500])
            except Exception as e:
                print("   ERRO:", e)
            depois = atuais()
            print("   empresas depois:", depois)
            if all(e in depois for e in empresas):
                print(f"   >>> FUNCIONOU com IND_STATUS={status}")
                break

    elif modo == "incluir":
        if api.em_producao:
            print("PARADO: este teste só roda em homologação.")
            return
        login, nome, email = sys.argv[2], sys.argv[3], sys.argv[4]
        senha_pir = gerar_senha(8)
        senha_ora = gerar_senha(20)
        usuario = PiramideAPI.montar_usuario(
            login=login, nome=nome, email=email,
            cod_perfil="21", cod_unid_origem="000", cod_cargo="06",
            senha_piramide=senha_pir, senha_oracle=senha_ora,
        )
        print("Já existe?", api.existe_usuario_bd(login))
        print("Resultado:", api.incluir_usuario(usuario, operador="teste_local"))
        print(f"Senha Pirâmide: {senha_pir}")
        print(f"Senha Oracle:   {senha_ora}")

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
