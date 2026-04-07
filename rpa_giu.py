"""RPA GIU Unimed - Ativa/Desativa usuarios no GIU."""

import sys
import time
import os
import traceback
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

GIU_URL = os.getenv('GIU_URL', 'https://giu.unimed.coop.br')
GIU_USERNAME = os.getenv('GIU_USERNAME')
GIU_PASSWORD = os.getenv('GIU_PASSWORD')

SUCESSO = 0
ERRO = 1
JA_INATIVO = 2
NAO_ENCONTRADO = 3

TENTATIVAS_EXECUCAO = [
    {"headless": False, "usar_chrome": True},
    {"headless": True, "usar_chrome": True},
    {"headless": True, "usar_chrome": False},
]


def _first_visible(page, selectors, timeout=8000):
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


def executar_giu_automatico(cpf_usuario, acao='bloquear'):
    if acao not in ('bloquear', 'desbloquear'):
        print(f"[GIU] Ação inválida: {acao}", file=sys.stderr)
        return ERRO

    if not GIU_USERNAME or not GIU_PASSWORD:
        print("[GIU] GIU_USERNAME/GIU_PASSWORD não definidos no .env.", file=sys.stderr)
        return ERRO

    with sync_playwright() as p:
        for indice, tentativa in enumerate(TENTATIVAS_EXECUCAO, start=1):
            browser = None
            context = None

            try:
                browser = p.chromium.launch(**_opcoes_lancamento(**tentativa))
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
                time.sleep(5)

                page.goto(f"{base_url}/gerenciarUsuarios", timeout=30000)
                page.wait_for_load_state("domcontentloaded")
                time.sleep(3)

                campo_busca = _first_visible(
                    page,
                    [
                        "input[placeholder*='Buscar Nome']",
                        "input[placeholder*='Buscar']",
                        "input[placeholder*='CPF']",
                        "input[type='search']",
                        "input[type='text']",
                    ],
                )
                if not campo_busca:
                    print("[GIU] Campo de busca não encontrado.", file=sys.stderr)
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

                try:
                    page.locator(
                        ".loading, .spinner, .v-overlay, .overlay, [class*='loading'], [class*='spinner']"
                    ).first.wait_for(state="hidden", timeout=5000)
                except Exception:
                    pass

                try:
                    icone_editar = page.locator(
                        "div.icone-acao.habilitado:visible, "
                        "[class*='icone-acao'][class*='habilitado']:visible, "
                        "button[aria-label*='Editar']:visible"
                    )
                    if icone_editar.count() == 0:
                        return NAO_ENCONTRADO
                except Exception:
                    return NAO_ENCONTRADO

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
                            return ERRO
                        page.evaluate("(el) => el.click()", handle)
                time.sleep(3)

                try:
                    status_texto = page.locator(
                        "span.fonte-secundaria.texto.label-campo, span:has-text('ATIVO'), span:has-text('INATIVO'), span:has-text('INATIVA')"
                    ).first
                    status_atual = status_texto.inner_text().strip().upper()

                    inativo = "INATIVA" in status_atual or "INATIVO" in status_atual
                    if acao == 'bloquear' and inativo:
                        return JA_INATIVO
                    if acao == 'desbloquear' and not inativo:
                        return JA_INATIVO
                except Exception:
                    pass

                try:
                    toggle = _first_visible(
                        page,
                        ["span.slider.round", "label.switch", "input[type='checkbox']"],
                        timeout=4000,
                    )
                    if not toggle:
                        print("[GIU] Toggle de ativação não encontrado.", file=sys.stderr)
                        return ERRO
                    toggle.click()
                except Exception:
                    print("[GIU] Falha ao clicar no toggle de ativação.", file=sys.stderr)
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


if __name__ == '__main__':
    if len(sys.argv) > 1:
        cpf = sys.argv[1]
    else:
        print("USO: python rpa_giu.py <cpf_usuario> [bloquear|desbloquear]")
        sys.exit(1)

    acao = sys.argv[2].lower() if len(sys.argv) > 2 else 'bloquear'
    resultado = executar_giu_automatico(cpf, acao)
    sys.exit(resultado)
