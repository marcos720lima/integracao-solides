"""RPA GIU Unimed - Ativa/Desativa usuarios no GIU."""

import re
import sys
import time
import os
import traceback
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

GIU_URL = os.getenv('GIU_URL', 'https://giu.unimed.coop.br')

# ZenRows Scraping Browser: resolve o desafio Cloudflare Turnstile no IP deles.
# Autorizado pela Unimed do Brasil (Edmilson) para a integracao com o GIU.
ZENROWS_API_KEY = os.getenv('ZENROWS_API_KEY', '').strip()
ZENROWS_BROWSER_WSS = os.getenv(
    'ZENROWS_BROWSER_WSS', 'wss://browser.zenrows.com'
).strip()
# Regiao do proxy do ZenRows. 'sa' (America do Sul) evita timeout ao alcancar
# servidores no Brasil, como o GIU. Vazio ou 'global' usa saida mundial.
ZENROWS_PROXY_REGION = os.getenv('ZENROWS_PROXY_REGION', 'sa').strip()
# Duracao da sessao do navegador remoto, em segundos (min 60, max 900). O padrao
# do ZenRows e 180s (3 min), curto demais para login + navegacao + inativacao.
def _normalizar_ttl(valor):
    """ZenRows espera duracao como string (ex: '10m', '90s'). Converte numero
    puro de segundos para esse formato."""
    valor = (valor or "").strip().lower()
    if not valor:
        return ""
    if valor.endswith("m") or valor.endswith("s"):
        return valor
    if valor.isdigit():
        seg = int(valor)
        return f"{seg // 60}m" if seg % 60 == 0 else f"{seg}s"
    return valor


ZENROWS_SESSION_TTL = _normalizar_ttl(os.getenv('ZENROWS_SESSION_TTL', '10m'))
GIU_USERNAME = os.getenv('GIU_USERNAME')
GIU_PASSWORD = os.getenv('GIU_PASSWORD')

SUCESSO = 0
ERRO = 1
JA_NO_ESTADO_DESEJADO = 2
NAO_ENCONTRADO = 3

ACOES_VALIDAS = {
    "bloquear": "bloquear",
    "desativar": "bloquear",
    "inativar": "bloquear",
    "desbloquear": "desbloquear",
    "ativar": "desbloquear",
}

ATIVO_STATUS = "ativo"
INATIVO_STATUS = "inativo"


def consultar_status_giu(cpf_usuario):
    """Consulta o status do usuario no GIU.

    Tenta primeiro a API oficial (giu-api), que e instantanea e nao depende de
    navegador nem passa pelo desafio do Cloudflare. Se a API nao estiver
    configurada ou falhar, cai no RPA por Playwright.
    """
    try:
        from painel.giu_api import GiuClient, GiuError

        giu = GiuClient()
        return giu.consultar_status(cpf_usuario)
    except ImportError:
        print("[GIU] Cliente da API indisponivel; usando RPA.", file=sys.stderr)
    except Exception as exc:
        print(f"[GIU] API falhou ({exc}); caindo para o RPA.", file=sys.stderr)

    return _consultar_status_giu_rpa(cpf_usuario)


def _consultar_status_giu_rpa(cpf_usuario):
    if not GIU_USERNAME or not GIU_PASSWORD:
        return ERRO, "GIU_USERNAME/GIU_PASSWORD não definidos no .env."

    with sync_playwright() as p:
        for indice, tentativa in enumerate(TENTATIVAS_EXECUCAO, start=1):
            browser = None
            context = None
            try:
                browser, usou_zenrows = _abrir_browser(p, tentativa)
                if usou_zenrows:
                    context = browser.contexts[0] if browser.contexts else browser.new_context(ignore_https_errors=True)
                    page = context.pages[0] if context.pages else context.new_page()
                else:
                    context = browser.new_context(ignore_https_errors=True)
                    page = context.new_page()

                base_url = GIU_URL.rstrip("/")
                page.goto(f"{base_url}/login", timeout=60000)
                page.wait_for_load_state("domcontentloaded")
                time.sleep(2)

                campo_usuario = _first_visible(
                    page,
                    ["input[placeholder='Insira o CPF ou CNPJ']", "input[placeholder*='CPF']", "input[name*='cpf']", "input[type='text']"],
                )
                campo_senha = _first_visible(
                    page,
                    ["input[type='password'][placeholder='Insira a senha']", "input[placeholder*='senha']", "input[type='password']"],
                )

                if not campo_usuario or not campo_senha:
                    _capturar_diagnostico(page, "login")
                    return ERRO, "Campos de login não encontrados."

                campo_usuario.fill(GIU_USERNAME or "")
                time.sleep(0.5)
                campo_senha.fill(GIU_PASSWORD or "")
                time.sleep(0.5)

                botao_login = _first_visible(
                    page, ["button.unicomp-botao.primario", "button:has-text('Entrar')", "button[type='submit']"], timeout=5000,
                )
                if not botao_login:
                    return ERRO, "Botão de login não encontrado."

                botao_login.click()
                # via sessao remota o GIU pode demorar a processar e redirecionar;
                # espera ativamente sair da tela de login antes de decidir.
                for _ in range(20):
                    time.sleep(1)
                    try:
                        corpo_tmp = (page.content() or "").lower()
                        if any(m in corpo_tmp for m in
                               ("gerenciar usu", "suas aplica", "meu perfil")):
                            break
                    except Exception:
                        pass

                bloqueio = _detectar_bloqueio_login(page, base_url)
                if bloqueio:
                    _capturar_diagnostico(page, "poslogin")
                    return ERRO, bloqueio

                page.goto(f"{base_url}/gerenciarUsuarios", timeout=30000)
                page.wait_for_load_state("domcontentloaded")
                time.sleep(3)

                campo_busca = _first_visible(
                    page,
                    ["input[placeholder*='Buscar Nome']", "input[placeholder*='Buscar']", "input[placeholder*='CPF']", "input[type='search']", "input[type='text']"],
                )
                if not campo_busca:
                    return ERRO, "Campo de busca não encontrado."

                campo_busca.fill(cpf_usuario)
                time.sleep(1)

                botao_buscar = _first_visible(
                    page, ["button.fonte-secundaria.texto", "button:has-text('Buscar')", "button:has-text('Pesquisar')"], timeout=3000,
                )
                if botao_buscar:
                    botao_buscar.click()
                else:
                    campo_busca.press("Enter")
                time.sleep(3)

                try:
                    page.locator(
                        ".loading, .spinner, .v-overlay, .overlay, [class*='loading'], [class*='spinner']"
                    ).first.wait_for(state="hidden", timeout=5000)
                except Exception:
                    pass

                try:
                    icone_editar = page.locator(
                        "div.icone-acao.habilitado:visible, [class*='icone-acao'][class*='habilitado']:visible, button[aria-label*='Editar']:visible"
                    )
                    if icone_editar.count() == 0:
                        return NAO_ENCONTRADO, None
                except Exception:
                    return NAO_ENCONTRADO, None

                alvo = icone_editar.first
                try:
                    alvo.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass

                try:
                    alvo.click(timeout=7000)
                except Exception:
                    try:
                        alvo.click(timeout=5000, force=True)
                    except Exception:
                        handle = alvo.element_handle()
                        if not handle:
                            return ERRO, "Não consegui abrir o cadastro do usuário."
                        page.evaluate("(el) => el.click()", handle)
                time.sleep(3)

                # aguarda a tela de edicao abrir (rota "Editar usuario")
                for _ in range(15):
                    try:
                        corpo_ed = (page.content() or "").lower()
                        if "editar usu" in corpo_ed or "dados b" in corpo_ed or "status da conta" in corpo_ed:
                            break
                    except Exception:
                        pass
                    time.sleep(1)

                try:
                    status_texto = page.locator(
                        "span.fonte-secundaria.texto.label-campo, span:has-text('ATIVO'), span:has-text('INATIVO'), span:has-text('INATIVA')"
                    ).first
                    status_atual = status_texto.inner_text().strip().upper()
                    inativo = "INATIVA" in status_atual or "INATIVO" in status_atual
                    return (INATIVO_STATUS if inativo else ATIVO_STATUS), cpf_usuario
                except Exception as e:
                    return ERRO, str(e)

            except Exception as exc:
                print(f"[GIU] [status] Tentativa {indice} falhou: {exc}", file=sys.stderr)
            finally:
                if context:
                    try:
                        context.close()
                    except Exception:
                        pass
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
                time.sleep(1)

        return ERRO, "Todas as tentativas falharam."


TENTATIVAS_EXECUCAO = [
    # Em VM/Windows, o "channel=chrome" pode fechar/crashar cedo; comece pelo Chromium do Playwright.
    {"headless": True, "usar_chrome": False},
    {"headless": True, "usar_chrome": True},
    {"headless": False, "usar_chrome": True},
]


def _first_visible(page, selectors, timeout=15000):
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout)
            return locator
        except Exception:
            continue
    return None


def _opcoes_lancamento(headless, usar_chrome):
    opcoes = {
        "headless": headless,
        "args": [
            "--disable-dev-shm-usage",
            "--disable-backgrounding-occluded-windows",
            "--disable-background-timer-throttling",
            "--disable-breakpad",
            # VMs costumam ter driver/GPU instável; isso reduz crash no start.
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    }
    if not headless:
        opcoes["args"].extend(["--window-size=900,650", "--window-position=50,50"])
    if usar_chrome:
        opcoes["channel"] = "chrome"
    return opcoes


def _capturar_diagnostico(page, prefixo):
    """Salva screenshot e HTML da pagina atual, para inspecionar o que o
    navegador remoto (ZenRows) carregou quando algo nao e encontrado."""
    import datetime
    carimbo = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"giu_debug_{prefixo}_{carimbo}"
    try:
        page.screenshot(path=f"{base}.png", full_page=True)
        print(f"[GIU] Screenshot salvo em {base}.png", file=sys.stderr)
    except Exception as e:
        print(f"[GIU] Falha ao salvar screenshot: {e}", file=sys.stderr)
    try:
        with open(f"{base}.html", "w", encoding="utf-8") as f:
            f.write(page.content() or "")
        print(f"[GIU] HTML salvo em {base}.html", file=sys.stderr)
    except Exception as e:
        print(f"[GIU] Falha ao salvar HTML: {e}", file=sys.stderr)
    try:
        print(f"[GIU] URL no momento da falha: {page.url}", file=sys.stderr)
    except Exception:
        pass


def _detectar_bloqueio_login(page, base_url):
    """Apos o clique em Entrar, distingue bloqueio Cloudflare de login normal.

    Retorna uma mensagem de erro se detectar que o login nao passou, ou None
    se seguiu para dentro do sistema. Sem isso, um bloqueio do Turnstile faz o
    fluxo reportar "usuario nao encontrado", mascarando a real causa.
    """
    try:
        url_atual = (page.url or "").lower()
    except Exception:
        url_atual = ""
    try:
        corpo = (page.content() or "").lower()
    except Exception:
        corpo = ""

    # Verificacao POSITIVA de que entrou: a home da versao 9.1.16 mostra o menu
    # e os cards. Se qualquer marca de "logado" aparece, o login passou -
    # independentemente da URL (SPA Vue usa rota em hash e pode manter "login"
    # em pedacos do bundle).
    marcas_logado = [
        "gerenciar usu", "suas aplica", "meu perfil", "sair do portal",
        "mainacessoautorizado",
    ]
    if any(m in corpo for m in marcas_logado):
        return None

    # Nao confirmou login. Distingue desafio Cloudflare de credencial recusada.
    if True:
        marcas_desafio = [
            "desafio de verifica", "challenge", "turnstile", "cf-chl",
            "cloudflare", "verify you are human", "confirme que voc",
        ]
        if any(m in corpo for m in marcas_desafio):
            return ("Bloqueado pelo desafio Cloudflare (Turnstile) na tela de "
                    "login. Verifique a integracao com o ZenRows "
                    "(ZENROWS_API_KEY).")
        return "Login nao concluido (ainda na tela de login apos enviar as credenciais)."
    return None


def _abrir_browser(p, tentativa):
    """Abre o navegador para o RPA do GIU.

    Se ZENROWS_API_KEY estiver definido, conecta ao Scraping Browser do ZenRows
    via CDP: a navegacao roda na infraestrutura deles, que resolve o desafio
    Cloudflare Turnstile no proprio IP. Caso contrario, lanca o Chromium local
    (comportamento antigo, que nao passa pelo Turnstile).

    Retorna (browser, usou_zenrows).
    """
    if ZENROWS_API_KEY:
        params = [f"apikey={ZENROWS_API_KEY}"]
        if ZENROWS_PROXY_REGION and ZENROWS_PROXY_REGION.lower() != 'global':
            params.append(f"proxy_region={ZENROWS_PROXY_REGION}")
        if ZENROWS_SESSION_TTL:
            params.append(f"session_ttl={ZENROWS_SESSION_TTL}")
        # nao duplica apikey se a URL base ja trouxer query string
        base = ZENROWS_BROWSER_WSS.split('?', 1)[0]
        url = base + '?' + '&'.join(params)
        browser = p.chromium.connect_over_cdp(url, timeout=120000)
        return browser, True

    browser = p.chromium.launch(**_opcoes_lancamento(**tentativa))
    return browser, False


def _erro_navegador_fechado(exc):
    msg = str(exc)
    return "Target page, context or browser has been closed" in msg or "TargetClosedError" in msg


def _aguardar_carregamento(page, timeout_s=90):
    """Espera o spinner "Carregando dados..." do GIU sumir.

    Retorna True quando nao ha spinner visivel, False se estourar o tempo.
    """
    spinner = page.locator(".vue-simple-spinner-text", has_text="Carregando dados")
    fim = time.time() + timeout_s
    while time.time() < fim:
        try:
            visivel = any(spinner.nth(i).is_visible() for i in range(spinner.count()))
            if not visivel:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _ler_status_inativo(page):
    """Le o status da conta na tela de edicao do GIU.

    O rotulo do status e um <span class="... label-campo verdadeiro"> ATIVA </span>
    (ou "falso" quando INATIVA). Retorna True = INATIVA, False = ATIVA,
    None = nao conseguiu ler.
    """
    try:
        label = page.locator("span.label-campo.verdadeiro, span.label-campo.falso").first
        label.wait_for(state="visible", timeout=8000)
        classe = (label.get_attribute("class") or "").lower()
        texto = (label.inner_text() or "").strip().upper()
    except Exception:
        return None
    # INATIV e checado primeiro, porque "ATIVA" esta contido em "INATIVA"
    if "falso" in classe or texto.startswith("INATIV"):
        return True
    if "verdadeiro" in classe or texto.startswith("ATIV"):
        return False
    return None


def _alternar_toggle(page, estado_antes):
    """Clica no toggle (span.slider.round) e CONFIRMA que o status mudou.

    Tenta 3 jeitos de clicar e para assim que o status mudar. Se nao
    conseguir reler o status, para imediatamente para nao clicar de novo
    e desfazer a alteracao.
    """
    metodos = [
        ("clique normal", lambda: page.locator("span.slider.round:visible").first.click(timeout=5000)),
        ("clique forcado", lambda: page.locator("span.slider.round:visible").first.click(timeout=5000, force=True)),
        ("clique via JS", lambda: page.evaluate("document.querySelector('span.slider.round')?.click()")),
    ]
    for nome, acao_clique in metodos:
        try:
            acao_clique()
        except Exception as exc:
            print(f"[GIU] Toggle ({nome}) deu erro: {exc}", file=sys.stderr)
        time.sleep(1.5)
        depois = _ler_status_inativo(page)
        if depois is None:
            return False
        if depois != estado_antes:
            print(f"[GIU] Toggle alterado com sucesso ({nome}).", file=sys.stderr)
            return True
        print(f"[GIU] Toggle ({nome}) nao mudou o status, tentando outro jeito...", file=sys.stderr)
    return False


def executar_giu_automatico(cpf_usuario, acao='desativar'):
    acao_normalizada = ACOES_VALIDAS.get((acao or '').lower())
    if acao_normalizada is None:
        print(f"[GIU] Ação inválida: {acao}", file=sys.stderr)
        return ERRO
    acao = acao_normalizada

    if not GIU_USERNAME or not GIU_PASSWORD:
        print("[GIU] GIU_USERNAME/GIU_PASSWORD não definidos no .env.", file=sys.stderr)
        return ERRO

    with sync_playwright() as p:
        for indice, tentativa in enumerate(TENTATIVAS_EXECUCAO, start=1):
            browser = None
            context = None

            try:
                browser, usou_zenrows = _abrir_browser(p, tentativa)
                if usou_zenrows:
                    context = browser.contexts[0] if browser.contexts else browser.new_context(ignore_https_errors=True)
                    page = context.pages[0] if context.pages else context.new_page()
                else:
                    context = browser.new_context(ignore_https_errors=True)
                    page = context.new_page()

                base_url = GIU_URL.rstrip("/")
                page.goto(f"{base_url}/login", timeout=60000)
                page.wait_for_load_state("domcontentloaded")
                time.sleep(2)

                campo_usuario = _first_visible(
                    page,
                    [
                        "input[placeholder='Insira o CPF ou CNPJ']",
                        "input[placeholder*='CPF']",
                        "input[name*='cpf']",
                        "input[type='text']",
                    ],
                )
                campo_senha = _first_visible(
                    page,
                    [
                        "input[type='password'][placeholder='Insira a senha']",
                        "input[placeholder*='senha']",
                        "input[type='password']",
                    ],
                )

                if not campo_usuario or not campo_senha:
                    _capturar_diagnostico(page, "login")
                    print("[GIU] Campos de login não encontrados.", file=sys.stderr)
                    return ERRO

                campo_usuario.fill(GIU_USERNAME or "")
                time.sleep(0.5)
                campo_senha.fill(GIU_PASSWORD or "")
                time.sleep(0.5)

                botao_login = _first_visible(
                    page,
                    [
                        "button.unicomp-botao.primario",
                        "button:has-text('Entrar')",
                        "button[type='submit']",
                    ],
                    timeout=5000,
                )
                if not botao_login:
                    print("[GIU] Botão de login não encontrado.", file=sys.stderr)
                    return ERRO

                botao_login.click()
                # via sessao remota o GIU pode demorar a processar e redirecionar;
                # espera ativamente sair da tela de login antes de decidir.
                for _ in range(20):
                    time.sleep(1)
                    try:
                        corpo_tmp = (page.content() or "").lower()
                        if any(m in corpo_tmp for m in
                               ("gerenciar usu", "suas aplica", "meu perfil")):
                            break
                    except Exception:
                        pass

                bloqueio = _detectar_bloqueio_login(page, base_url)
                if bloqueio:
                    _capturar_diagnostico(page, "poslogin")
                    print(f"[GIU] {bloqueio}", file=sys.stderr)
                    return ERRO

                # Navega ate "Gerenciar usuarios". Na SPA Vue 9.1.16 o deep-link
                # por URL nem sempre dispara a rota, entao ha um plano B: clicar
                # no card/menu "Gerenciar usuarios" da home.
                seletores_busca = [
                    "input[placeholder*='Buscar Nome']",
                    "input[placeholder*='Login do usu']",
                    "input[placeholder*='Buscar']",
                    "input[placeholder*='documento']",
                    "input[type='search']",
                ]
                campo_busca = None

                # Estrategia 1: clicar no card "Gerenciar usuarios" da home (ja
                # estamos nela apos o login). O card tem id proprio; clicamos nele
                # ou em qualquer ancestral clicavel.
                def _tentar_card():
                    for sel in [
                        "#id_gerenciar_usuarios_card",
                        "div.cartao-icone:has-text('Gerenciar')",
                        "h2:has-text('Gerenciar usuários')",
                        "div:has-text('Gerenciar usuários')",
                    ]:
                        try:
                            loc = page.locator(sel).first
                            if loc.count() and loc.is_visible():
                                loc.scroll_into_view_if_needed(timeout=3000)
                                loc.click(timeout=4000)
                                return True
                        except Exception:
                            continue
                    # ultimo recurso: clique via JS no card por id
                    try:
                        page.evaluate(
                            "document.querySelector('#id_gerenciar_usuarios_card')?.click()"
                        )
                        return True
                    except Exception:
                        return False

                for tentativa_nav in range(3):
                    if tentativa_nav == 0:
                        _tentar_card()
                    elif tentativa_nav == 1:
                        # deep-link direto
                        try:
                            page.goto(f"{base_url}/#/gerenciarUsuarios", timeout=20000)
                        except Exception:
                            pass
                    else:
                        # volta pra home e tenta o card de novo
                        try:
                            page.goto(f"{base_url}/#/home", timeout=15000)
                            time.sleep(1.5)
                        except Exception:
                            pass
                        _tentar_card()

                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except Exception:
                        pass
                    time.sleep(2)
                    campo_busca = _first_visible(page, seletores_busca, timeout=6000)
                    if campo_busca:
                        break

                if not campo_busca:
                    _capturar_diagnostico(page, "gerenciar")
                    print(f"[GIU] Campo de busca não encontrado. URL: {page.url}",
                          file=sys.stderr)
                    return ERRO

                # espera a lista inicial terminar de carregar antes de buscar
                if not _aguardar_carregamento(page):
                    _capturar_diagnostico(page, "carregando_lista")
                    print("[GIU] Lista de usuarios nao terminou de carregar.", file=sys.stderr)
                    return ERRO

                campo_busca.fill(cpf_usuario)
                time.sleep(1)

                botao_buscar = _first_visible(
                    page,
                    [
                        "button.fonte-secundaria.texto",
                        "button:has-text('Buscar')",
                        "button:has-text('Pesquisar')",
                    ],
                    timeout=3000,
                )
                if botao_buscar:
                    botao_buscar.click()
                else:
                    campo_busca.press("Enter")
                time.sleep(3)

                # espera o resultado da busca carregar de verdade (via ZenRows
                # pode levar bem mais que 5s). Se nao carregar, e ERRO, e nao
                # "nao encontrado", pra nao mascarar lentidao como usuario inexistente.
                if not _aguardar_carregamento(page):
                    _capturar_diagnostico(page, "carregando_busca")
                    print("[GIU] Resultado da busca nao terminou de carregar.", file=sys.stderr)
                    return ERRO
                time.sleep(1)

                # ---------- 1) acha a linha do CPF certo no resultado ----------
                # So clica em "editar" na linha que contem o CPF buscado, para
                # nunca abrir o cadastro de outra pessoa.
                cpf_digitos = re.sub(r"\D", "", cpf_usuario)
                linhas = page.locator("tbody tr")
                linha_alvo = None
                try:
                    for i in range(linhas.count()):
                        texto_linha = re.sub(r"\D", "", linhas.nth(i).inner_text() or "")
                        if cpf_digitos and cpf_digitos in texto_linha:
                            linha_alvo = linhas.nth(i)
                            break
                except Exception:
                    linha_alvo = None

                if linha_alvo is None:
                    _capturar_diagnostico(page, "resultado_busca")
                    print(f"[GIU] CPF final {cpf_digitos[-2:]} nao aparece no resultado da busca.", file=sys.stderr)
                    return NAO_ENCONTRADO

                alvo = linha_alvo.locator(
                    "div.icone-acao.habilitado, [class*='icone-acao'][class*='habilitado']"
                ).first
                if alvo.count() == 0:
                    _capturar_diagnostico(page, "resultado_busca")
                    print("[GIU] Linha do CPF encontrada, mas sem icone de editar.", file=sys.stderr)
                    return ERRO

                # ---------- 2) abre o cadastro ----------
                try:
                    alvo.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass

                try:
                    alvo.click(timeout=7000)
                except Exception:
                    try:
                        alvo.click(timeout=5000, force=True)
                    except Exception:
                        handle = alvo.element_handle()
                        if not handle:
                            return ERRO
                        page.evaluate("(el) => el.click()", handle)
                time.sleep(3)

                # aguarda a tela de edicao abrir (rota "Editar usuario")
                for _ in range(15):
                    try:
                        corpo_ed = (page.content() or "").lower()
                        if "editar usu" in corpo_ed or "dados b" in corpo_ed or "status da conta" in corpo_ed:
                            break
                    except Exception:
                        pass
                    time.sleep(1)

                # ---------- 3) le o status; se nao souber, NAO mexe ----------
                inativo = _ler_status_inativo(page)
                if inativo is None:
                    _capturar_diagnostico(page, "status")
                    print("[GIU] Nao consegui ler o status da conta; nada foi alterado.", file=sys.stderr)
                    return ERRO

                if acao == 'bloquear' and inativo:
                    return JA_NO_ESTADO_DESEJADO
                if acao == 'desbloquear' and not inativo:
                    return JA_NO_ESTADO_DESEJADO

                # ---------- 4) clica no toggle e confirma a mudanca ----------
                if not _alternar_toggle(page, inativo):
                    _capturar_diagnostico(page, "toggle")
                    print("[GIU] Nao consegui alterar o toggle de ativacao.", file=sys.stderr)
                    return ERRO

                time.sleep(2)

                botao_salvar = _first_visible(
                    page,
                    [
                        "button.unicomp-botao.primario:has-text('SALVAR')",
                        "button:has-text('Salvar')",
                        "button:has-text('SALVAR')",
                    ],
                    timeout=5000,
                )
                if not botao_salvar:
                    print("[GIU] Botão SALVAR não encontrado.", file=sys.stderr)
                    return ERRO
                botao_salvar.click()
                time.sleep(3)

                try:
                    botao_fechar = _first_visible(
                        page,
                        [
                            "button.unicomp-botao.primario:has-text('FECHAR')",
                            "button:has-text('Fechar')",
                            "button:has-text('FECHAR')",
                        ],
                        timeout=5000,
                    )
                    if botao_fechar:
                        botao_fechar.click()
                    time.sleep(2)
                except Exception:
                    pass

                return SUCESSO
            except Exception as exc:
                print(f"[GIU] Tentativa {indice} falhou: {exc}", file=sys.stderr)
                if _erro_navegador_fechado(exc):
                    print("[GIU] Chrome/contexto fechou inesperadamente (TargetClosedError).", file=sys.stderr)
                print(traceback.format_exc(), file=sys.stderr)
            finally:
                if context:
                    try:
                        context.close()
                    except Exception:
                        pass
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
                time.sleep(1)

        return ERRO


def ativar_usuario_giu(cpf_usuario):
    return executar_giu_automatico(cpf_usuario, acao='ativar')


def desativar_usuario_giu(cpf_usuario):
    return executar_giu_automatico(cpf_usuario, acao='desativar')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        cpf = sys.argv[1]
    else:
        print("USO: python rpa_giu.py <cpf_usuario> [ativar|desativar|status]")
        sys.exit(1)

    acao = sys.argv[2].lower() if len(sys.argv) > 2 else 'desativar'

    if acao == 'status':
        status, detalhe = consultar_status_giu(cpf)
        print(f"status={status} detalhe={detalhe}")
        sys.exit(SUCESSO)
    resultado = executar_giu_automatico(cpf, acao)
    sys.exit(resultado)
