"""RPA CRM JMJ - Ativa/Desativa usuarios no CRM."""

import os
import sys
import time
import traceback

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
        ],
    }
    if not headless:
        opcoes["args"].extend(["--window-size=600,400", "--window-position=3000,3000"])
    if usar_chrome:
        opcoes["channel"] = "chrome"
    return opcoes


def _erro_navegador_fechado(exc):
    msg = str(exc)
    return "Target page, context or browser has been closed" in msg or "TargetClosedError" in msg


def _executar_fluxo(page, email_usuario, acao):
    nome_usuario = email_usuario.split("@")[0].replace(".", " ").lower()

    page.goto(f"{CRM_URL}/#/authenticate", timeout=60000)
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    time.sleep(3)

    page.click("input[ng-model='credentials.username']")
    page.fill("input[ng-model='credentials.username']", "")
    page.type("input[ng-model='credentials.username']", CRM_USERNAME, delay=100)

    page.click("input[name='senha']")
    page.fill("input[name='senha']", "")
    page.type("input[name='senha']", CRM_PASSWORD, delay=100)

    # Em algumas versões do CRM o Angular pode não estar no escopo.
    try:
        page.evaluate(
            "angular.element(document.querySelector(\"input[ng-model='credentials.username']\")).scope().$apply()"
        )
        page.evaluate("angular.element(document.querySelector(\"input[name='senha']\")).scope().$apply()")
    except Exception:
        pass

    page.click("[ng-click='login(credentials)']")
    time.sleep(8)

    page.goto(f"{CRM_URL}/#/configuracoes/usuarios", timeout=30000)
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    time.sleep(3)

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
