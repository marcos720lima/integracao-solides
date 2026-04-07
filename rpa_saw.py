"""RPA SAW - Ativa/Desativa usuarios no SAW."""

import os
import sys
import time
import traceback

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

SAW_URL = os.getenv('SAW_URL', 'https://saw.trixti.com.br/saw')
SAW_USERNAME = os.getenv('SAW_USERNAME')
SAW_PASSWORD = os.getenv('SAW_PASSWORD')

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
    page.goto(f"{SAW_URL}/Logar.do?method=abrirSAW", timeout=60000)
    page.fill("input[name='j_username']", SAW_USERNAME)
    page.fill("input[name='j_password']", SAW_PASSWORD)
    page.click("input#submitForm")
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    time.sleep(2)

    page.goto(f"{SAW_URL}/ManterUsuario.do?comando=abrirTelaInicialDeUsuario", timeout=60000)
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    time.sleep(2)

    campo = "input[name='filtroDePesquisaDeUsuarios.usuario.email']"
    page.fill(campo, email_usuario)
    page.press(campo, "Enter")
    time.sleep(3)

    icone_desativar = page.locator("img[src*='desativarUsuario']")
    icone_ativar = page.locator("img[src*='ativarUsuario']")

    if icone_desativar.count() == 0 and icone_ativar.count() == 0:
        return NAO_ENCONTRADO

    if acao == "bloquear" and icone_desativar.count() == 0 and icone_ativar.count() > 0:
        return JA_INATIVO
    if acao == "desbloquear" and icone_ativar.count() == 0 and icone_desativar.count() > 0:
        return JA_INATIVO

    page.evaluate("window.confirm = () => true;")

    try:
        if acao == "bloquear":
            icone_desativar.first.click()
        else:
            icone_ativar.first.click()
    except Exception:
        try:
            if acao == "bloquear":
                page.click("img[src*='desativarUsuario']")
            else:
                page.click("img[src*='ativarUsuario']")
        except Exception:
            if acao == "bloquear":
                page.click("img[title*='Desativar'], img[alt*='Desativar']")
            else:
                page.click("img[title*='Ativar'], img[alt*='Ativar']")

    time.sleep(3)

    page.reload()
    time.sleep(2)

    page.fill(campo, email_usuario)
    page.press(campo, "Enter")
    time.sleep(3)

    icone_ativar_depois = page.locator("img[src*='ativarUsuario']")
    icone_desativar_depois = page.locator("img[src*='desativarUsuario']")

    if acao == "bloquear":
        if icone_ativar_depois.count() > 0 and icone_desativar_depois.count() == 0:
            return SUCESSO
        if icone_desativar_depois.count() > 0:
            return ERRO
    else:
        if icone_desativar_depois.count() > 0 and icone_ativar_depois.count() == 0:
            return SUCESSO
        if icone_ativar_depois.count() > 0:
            return ERRO
    return SUCESSO


def executar_saw_automatico(email_usuario, acao='bloquear'):
    if acao not in ("bloquear", "desbloquear"):
        print(f"[SAW] Ação inválida: {acao}", file=sys.stderr)
        return ERRO

    if not SAW_USERNAME or not SAW_PASSWORD:
        print("[SAW] SAW_USERNAME/SAW_PASSWORD não definidos no .env.", file=sys.stderr)
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

                print(f"[SAW] Tentativa {indice}: erro funcional no fluxo.", file=sys.stderr)
            except Exception as exc:
                print(f"[SAW] Tentativa {indice} falhou: {exc}", file=sys.stderr)
                if _erro_navegador_fechado(exc):
                    print("[SAW] Chrome/contexto fechou inesperadamente (TargetClosedError).", file=sys.stderr)
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
        print("USO: python rpa_saw.py <email_usuario> [bloquear|desbloquear]")
        sys.exit(1)

    acao = sys.argv[2].lower() if len(sys.argv) > 2 else 'bloquear'
    resultado = executar_saw_automatico(email, acao)
    sys.exit(resultado)
