"""RPA Tasy EMR - Ativa/Inativa usuarios no Tasy"""

import sys
import time
import os
import traceback
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

TASY_URL = os.getenv('TASY_URL', 'https://tasy.unimedoestedopara.coop.br')
TASY_USERNAME = os.getenv('TASY_USERNAME')
TASY_PASSWORD = os.getenv('TASY_PASSWORD')

SUCESSO = 0
ERRO = 1
JA_INATIVO = 2
NAO_ENCONTRADO = 3


TENTATIVAS_EXECUCAO = [
    # Headful primeiro para acompanhar visualmente, depois headless.
    {"headless": False, "usar_chrome": True},
    {"headless": True, "usar_chrome": True},
    {"headless": True, "usar_chrome": False},
]


def _log(msg):
    print(f"[TASY] {msg}", file=sys.stderr)


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
        opcoes["args"].extend(["--window-size=1200,850", "--window-position=40,40"])
    if usar_chrome:
        opcoes["channel"] = "chrome"
    return opcoes


def _first_visible(page, selectors, timeout=15000):
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout)
            return locator
        except Exception:
            continue
    return None


def _salvar_debug(page, prefixo="tasy"):
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


def executar_tasy_automatico(nome_completo, nome_conta, acao='bloquear'):
    if acao not in ('bloquear', 'desbloquear'):
        _log(f"Ação inválida: {acao}")
        return ERRO

    if not TASY_USERNAME or not TASY_PASSWORD:
        _log("TASY_USERNAME/TASY_PASSWORD não definidos no .env.")
        return ERRO
    
    nome_conta_comparacao = nome_conta.lower().replace('.', ' ')
    
    with sync_playwright() as p:
        for indice, tentativa in enumerate(TENTATIVAS_EXECUCAO, start=1):
            browser = None
            context = None
            page = None
            try:
                _log(f"Tentativa {indice}: abrindo navegador (headless={tentativa['headless']}, chrome={tentativa['usar_chrome']})")
                browser = p.chromium.launch(**_opcoes_lancamento(**tentativa))
                context = browser.new_context(ignore_https_errors=True)
                page = context.new_page()

                _log("Abrindo Tasy")
                page.goto(f"{TASY_URL}/#/", wait_until="domcontentloaded", timeout=120000)
                page.wait_for_load_state("domcontentloaded", timeout=60000)
                time.sleep(2)

                _log("Logando")
                campo_user = _first_visible(page, ["input#loginUsername", "input[name='loginUsername']", "input[type='text']"], timeout=60000)
                campo_pass = _first_visible(page, ["input#loginPassword", "input[name='loginPassword']", "input[type='password']"], timeout=60000)
                botao_login = _first_visible(page, ["input.btn-green.w-login-button", "button:has-text('Entrar')", "button[type='submit']"], timeout=60000)
                if not campo_user or not campo_pass or not botao_login:
                    _log("Campos/botão de login não encontrados.")
                    _salvar_debug(page, "tasy_login")
                    return ERRO

                campo_user.fill(TASY_USERNAME)
                time.sleep(0.3)
                campo_pass.fill(TASY_PASSWORD)
                time.sleep(0.3)
                botao_login.click()
                time.sleep(4)

                try:
                    page.wait_for_load_state("networkidle", timeout=60000)
                except Exception:
                    pass
                time.sleep(2)

                _log("Abrindo módulo Administração do Sistema")
                try:
                    admin_modulo = page.locator("span.w-feature-app__name:has-text('Administração do Sistema')")
                    if admin_modulo.count() > 0:
                        admin_modulo.first.click()
                    else:
                        page.click("a:has-text('Administração do Sistema')")
                except Exception:
                    page.locator("text=Administração do Sistema").first.click()

                time.sleep(2)
                try:
                    page.wait_for_load_state("networkidle", timeout=60000)
                except Exception:
                    pass
                time.sleep(1)

                _log("Abrindo Cadastro de usuários")
                try:
                    usuarios_link = page.locator("text=Cadastro de usuários").first
                    if usuarios_link.is_visible():
                        usuarios_link.click()
                    else:
                        page.locator("span:has-text('Usuários')").first.click()
                except Exception:
                    pass
                time.sleep(2)

                _log(f"Filtrando por nome: {nome_completo}")
                campo_nome = _first_visible(page, ["input[name='NM_PESSOA']", "input[placeholder='Nome']", "input[type='text']"], timeout=60000)
                if not campo_nome:
                    _log("Campo de nome não encontrado.")
                    _salvar_debug(page, "tasy_filtro")
                    return ERRO
                campo_nome.fill(nome_completo)
                time.sleep(0.8)

                botao_filtrar = _first_visible(page, ["button:has-text('Filtrar')", "span:has-text('Filtrar')"], timeout=30000)
                if botao_filtrar:
                    botao_filtrar.click()
                time.sleep(2)
                try:
                    page.wait_for_load_state("networkidle", timeout=30000)
                except Exception:
                    pass
                time.sleep(1)

                if page.locator("text=Esta lista está vazia").count() > 0:
                    return NAO_ENCONTRADO

                linhas = page.locator("div.ui-widget-content.slick-row").all()
                linha_usuario = None
                nome_partes = nome_conta_comparacao.split()
                for linha in linhas:
                    try:
                        texto_linha = linha.inner_text().lower()
                        if all(parte in texto_linha for parte in nome_partes):
                            linha_usuario = linha
                            break
                    except Exception:
                        continue

                if not linha_usuario:
                    return NAO_ENCONTRADO

                _log(f"Abrindo usuário: {nome_conta}")
                try:
                    checkbox = linha_usuario.locator("input[type='checkbox'], label.wcheckbox-inputlabel").first
                    if checkbox.count() > 0:
                        checkbox.click()
                    else:
                        linha_usuario.click()
                except Exception:
                    linha_usuario.click()
                time.sleep(1)

                try:
                    page.locator("span.handlebar-button-label:has-text('Ver')").first.click()
                except Exception:
                    try:
                        page.locator("button:has-text('Ver')").first.click()
                    except Exception:
                        page.locator(".handlebar-button:has-text('Ver'), .ng-scope.handlebar-button:has-text('Ver')").first.click()

                time.sleep(2)
                try:
                    page.wait_for_load_state("networkidle", timeout=30000)
                except Exception:
                    pass

                radio_ativo = page.locator("input[type='radio'][value='A'], label:has-text('Ativo') input[type='radio']").first
                radio_inativo = page.locator("input[type='radio'][value='I'], label:has-text('Inativo') input[type='radio']").first

                esta_ativo = True
                try:
                    if radio_ativo.is_checked():
                        esta_ativo = True
                    elif radio_inativo.is_checked():
                        esta_ativo = False
                except Exception:
                    esta_ativo = True

                if acao == 'bloquear' and not esta_ativo:
                    try:
                        inativo_selecionado = page.locator(
                            "label:has-text('Inativo').selected, input[type='radio']:checked + label:has-text('Inativo')"
                        ).count()
                        if inativo_selecionado > 0:
                            page.locator("span:has-text('Cancelar'), button:has-text('Cancelar')").first.click()
                            time.sleep(1)
                            return JA_INATIVO
                    except Exception:
                        return JA_INATIVO
                if acao == 'desbloquear' and esta_ativo:
                    try:
                        page.locator("span:has-text('Cancelar'), button:has-text('Cancelar')").first.click()
                    except Exception:
                        pass
                    time.sleep(1)
                    return JA_INATIVO

                _log("Alterando status e salvando")
                try:
                    if acao == 'bloquear':
                        page.locator("label:has-text('Inativo')").first.click()
                    else:
                        page.locator("label:has-text('Ativo')").first.click()
                except Exception:
                    try:
                        if acao == 'bloquear':
                            radio_inativo.click()
                        else:
                            radio_ativo.click()
                    except Exception:
                        page.click("text=Inativo" if acao == 'bloquear' else "text=Ativo")

                time.sleep(0.8)
                try:
                    page.locator("span.wbutton-text:has-text('Salvar')").first.click()
                except Exception:
                    try:
                        page.locator("div.wbutton-container.btn-blue:has-text('Salvar')").first.click()
                    except Exception:
                        page.locator("button:has-text('Salvar')").first.click()

                time.sleep(2)
                try:
                    page.wait_for_load_state("networkidle", timeout=30000)
                except Exception:
                    pass

                _log("Concluído com sucesso")
                return SUCESSO

            except Exception as exc:
                _log(f"Tentativa {indice} falhou: {exc}")
                if page:
                    _salvar_debug(page, "tasy_erro")
                print(traceback.format_exc(), file=sys.stderr)
            finally:
                time.sleep(1)
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

        return ERRO


if __name__ == '__main__':
    acao = 'bloquear'
    if len(sys.argv) >= 4:
        # python rpa_tasy.py "<nome_completo>" "<nome_conta>" [acao]
        nome_completo = sys.argv[1]
        nome_conta = sys.argv[2]
        acao = sys.argv[3].lower()
    elif len(sys.argv) == 3:
        # Compatibilidade:
        # - server.py chama com: rpa_tasy.py "<nome_completo>" "<nome_conta>"
        # - modo alternativo: rpa_tasy.py "<email>" [acao]
        arg1 = sys.argv[1]
        arg2 = sys.argv[2]
        if "@" in arg1:
            email = arg1
            nome_conta = email.split('@')[0]
            nome_completo = nome_conta.replace('.', ' ').title()
            acao = arg2.lower()
        else:
            nome_completo = arg1
            nome_conta = arg2
    elif len(sys.argv) == 2:
        email = sys.argv[1]
        nome_conta = email.split('@')[0]
        nome_completo = nome_conta.replace('.', ' ').title()
    else:
        print("USO: python rpa_tasy.py <nome_completo> <nome_conta> [bloquear|desbloquear]")
        print("  ou: python rpa_tasy.py <email> [bloquear|desbloquear]")
        sys.exit(1)
    
    resultado = executar_tasy_automatico(nome_completo, nome_conta, acao)
    sys.exit(resultado)
