"""RPA CRM JMJ - Ativa/Desativa usuarios no CRM."""

import os
import sys
import time
import traceback
from datetime import datetime

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

CRM_URL = os.getenv('CRM_URL', 'https://oestedopara.jmjsistemas.com.br/crm')
CRM_USERNAME = os.getenv('CRM_USERNAME')
CRM_PASSWORD = os.getenv('CRM_PASSWORD')

SUCESSO = 0
ERRO = 1
JA_INATIVO = 2
NAO_ENCONTRADO = 3

TENTATIVAS_EXECUCAO = [
    # Priorize headful para acompanhar visualmente; fallback para headless se necessário.
    {"headless": False, "usar_chrome": True},
    {"headless": True, "usar_chrome": True},
    {"headless": True, "usar_chrome": False},
]


def _opcoes_lancamento(headless, usar_chrome):
    opcoes = {
        "headless": headless,
        "args": [
            "--disable-dev-shm-usage",
            "--disable-backgrounding-occluded-windows",
            "--disable-background-timer-throttling",
            "--disable-breakpad",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    }
    if not headless:
        opcoes["args"].extend(["--window-size=1100,800", "--window-position=40,40"])
    if usar_chrome:
        opcoes["channel"] = "chrome"
    return opcoes


def _erro_navegador_fechado(exc):
    msg = str(exc)
    return "Target page, context or browser has been closed" in msg or "TargetClosedError" in msg


def _log(msg):
    print(f"[CRM] {msg}", file=sys.stderr)


def _first_visible(page, selectors, timeout=15000):
    if not selectors:
        return None

    # Alguns logins SPA demoram para renderizar; precisamos respeitar o timeout total
    # sem ficar "preso" muito tempo em um único seletor.
    deadline = time.time() + (timeout / 1000.0)

    while time.time() < deadline:
        restante_ms = int(max(0, (deadline - time.time()) * 1000))
        # Tenta rápido por seletor, repetindo até o timeout total.
        por_seletor_ms = min(4000, max(500, int(restante_ms / max(1, len(selectors)))))

        for selector in selectors:
            try:
                locator = page.locator(selector).first
                locator.wait_for(state="visible", timeout=por_seletor_ms)
                return locator
            except Exception:
                continue

        time.sleep(0.3)

    return None


def _salvar_debug(page, prefixo="crm"):
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"debug_{prefixo}_{ts}"
        page.screenshot(path=f"{base}.png", full_page=True)
        try:
            html = page.content()
            with open(f"{base}.html", "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass
        _log(f"Debug salvo: {base}.png / {base}.html (url={page.url})")
    except Exception:
        pass


def _executar_fluxo(page, email_usuario, acao):
    nome_usuario = email_usuario.split("@")[0].replace(".", " ").lower()

    # CRM é SPA (Angular): esperar por "load" pode ficar pendurado por assets/requests.
    # Preferimos domcontentloaded e aguardamos o campo de login aparecer.
    _log(f"Abrindo login: {CRM_URL}/#/authenticate")
    page.goto(f"{CRM_URL}/#/authenticate", wait_until="domcontentloaded", timeout=120000)
    page.wait_for_load_state("domcontentloaded", timeout=60000)
    time.sleep(3)

    _log("Procurando campos de login")
    campo_usuario = _first_visible(
        page,
        [
            "input[ng-model='credentials.username']",
            "input[name='username']",
            "input[name='usuario']",
            "input[type='email']",
            "input[placeholder*='Usu']",
            "input[placeholder*='E-mail']",
            "input[placeholder*='Email']",
            "input[type='text']",
        ],
        timeout=60000,
    )
    campo_senha = _first_visible(
        page,
        [
            "input[name='senha']",
            "input[name='password']",
            "input[type='password']",
            "input[placeholder*='Senha']",
        ],
        timeout=60000,
    )

    if not campo_usuario or not campo_senha:
        _log("Campos de login não encontrados (tela pode ter mudado/SSO/captcha/erro de acesso).")
        _salvar_debug(page, "crm_login")
        return ERRO

    _log("Preenchendo usuário/senha")
    campo_usuario.click()
    campo_usuario.fill("")
    campo_usuario.type(CRM_USERNAME, delay=100)

    campo_senha.click()
    campo_senha.fill("")
    campo_senha.type(CRM_PASSWORD, delay=100)

    # Em algumas versões do CRM o Angular pode não estar no escopo.
    try:
        page.evaluate(
            "angular.element(document.querySelector(\"input[ng-model='credentials.username']\")).scope().$apply()"
        )
        page.evaluate("angular.element(document.querySelector(\"input[name='senha']\")).scope().$apply()")
    except Exception:
        pass

    _log("Clicando em Entrar/Login")
    botao_login = _first_visible(
        page,
        [
            "[ng-click='login(credentials)']",
            "button[type='submit']",
            "button:has-text('Entrar')",
            "button:has-text('Login')",
        ],
        timeout=15000,
    )
    if not botao_login:
        _log("Botão de login não encontrado.")
        _salvar_debug(page, "crm_login_sem_botao")
        return ERRO
    botao_login.click()
    time.sleep(8)

    _log("Abrindo página de usuários")
    page.goto(f"{CRM_URL}/#/configuracoes/usuarios", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    time.sleep(3)

    _log(f"Pesquisando usuário: {email_usuario}")
    page.fill("input[ng-model='search.email']", email_usuario)
    page.click("button[ng-click='pesquisar(search)']")
    time.sleep(3)

    divs = page.locator("div").all()
    usuario_divs = []

    for i, div in enumerate(divs):
        try:
            text = div.inner_text().lower()
            if nome_usuario in text or email_usuario.lower() in text:
                usuario_divs.append((i, div))
        except Exception:
            continue

    if not usuario_divs:
        try:
            primeira_linha = page.locator("tr.ng-scope, div.usuario-item, div[ng-repeat]").first
            if primeira_linha.is_visible():
                usuario_divs.append((0, primeira_linha))
        except Exception:
            pass

    if not usuario_divs:
        return NAO_ENCONTRADO

    sucesso = False
    for _, div in usuario_divs:
        try:
            div.click()
            time.sleep(2)

            menus = page.locator(".angular-bootstrap-contextmenu, .dropdown-menu, ul[role='menu'], .contextmenu").all()
            menus_visiveis = [m for m in menus if m.is_visible()]

            for menu in menus_visiveis:
                editar_elementos = menu.locator("a, span, div").all()
                for elem in editar_elementos:
                    try:
                        if elem.is_visible():
                            text = elem.inner_text().strip()
                            if text and "editar" in text.lower():
                                elem.click()
                                time.sleep(5)

                                if page.locator("jmj-toggle").count() > 0 or page.locator("strong:has-text('Ativo')").count() > 0:
                                    sucesso = True
                                    break
                    except Exception:
                        continue
                if sucesso:
                    break
            if sucesso:
                break
        except Exception:
            continue

    if not sucesso:
        return NAO_ENCONTRADO

    try:
        toggle = page.locator("jmj-toggle button, button[tabindex='-1']").first
        toggle_class = toggle.get_attribute("class") or ""
        desligado = "off" in toggle_class.lower() or "inactive" in toggle_class.lower()
        if acao == "bloquear" and desligado:
            return JA_INATIVO
        if acao == "desbloquear" and not desligado:
            return JA_INATIVO
    except Exception:
        pass

    try:
        page.click("button[ng-click='ingDisabled ? ngModel = !ngModel : null']")
    except Exception:
        try:
            page.click("jmj-toggle button")
        except Exception:
            page.click("button[tabindex='-1']")

    time.sleep(2)

    page.click("button.btn.btn-flat.btn-tumblr:has-text('Salvar')")
    time.sleep(3)
    return SUCESSO


def executar_crm_automatico(email_usuario, acao='bloquear'):
    if acao not in ("bloquear", "desbloquear"):
        print(f"[CRM] Ação inválida: {acao}", file=sys.stderr)
        return ERRO

    if not CRM_USERNAME or not CRM_PASSWORD:
        print("[CRM] CRM_USERNAME/CRM_PASSWORD não definidos no .env.", file=sys.stderr)
        return ERRO

    with sync_playwright() as p:
        for indice, tentativa in enumerate(TENTATIVAS_EXECUCAO, start=1):
            browser = None
            context = None

            try:
                browser = p.chromium.launch(**_opcoes_lancamento(**tentativa))
                context = browser.new_context(ignore_https_errors=True)
                page = context.new_page()

                resultado = _executar_fluxo(page, email_usuario, acao)
                if resultado != ERRO:
                    return resultado

                print(f"[CRM] Tentativa {indice}: erro funcional no fluxo.", file=sys.stderr)
            except Exception as exc:
                print(f"[CRM] Tentativa {indice} falhou: {exc}", file=sys.stderr)
                if _erro_navegador_fechado(exc):
                    print("[CRM] Chrome/contexto fechou inesperadamente (TargetClosedError).", file=sys.stderr)
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


if __name__ == '__main__':
    if len(sys.argv) > 1:
        email = sys.argv[1]
    else:
        print("USO: python rpa_crm.py <email_usuario> [bloquear|desbloquear]")
        sys.exit(1)

    acao = sys.argv[2].lower() if len(sys.argv) > 2 else 'bloquear'
    resultado = executar_crm_automatico(email, acao)
    sys.exit(resultado)
