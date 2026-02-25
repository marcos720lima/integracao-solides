"""RPA SAW - Ativa/Desativa usuarios no SAW"""

import sys
import time
import os
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


def executar_saw_automatico(email_usuario, acao='bloquear'):
    if acao not in ('bloquear', 'desbloquear'):
        return ERRO

    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.launch(
                channel="chrome",
                headless=False,
                args=["--window-size=600,400", "--window-position=3000,3000"]
            )
            page = browser.new_page()
            
            try:
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

                if acao == 'bloquear' and icone_desativar.count() == 0 and icone_ativar.count() > 0:
                    return JA_INATIVO
                if acao == 'desbloquear' and icone_ativar.count() == 0 and icone_desativar.count() > 0:
                    return JA_INATIVO
                
                page.evaluate("window.confirm = () => true;")
                
                try:
                    if acao == 'bloquear':
                        icone_desativar.first.click()
                    else:
                        icone_ativar.first.click()
                except:
                    try:
                        if acao == 'bloquear':
                            page.click("img[src*='desativarUsuario']")
                        else:
                            page.click("img[src*='ativarUsuario']")
                    except:
                        if acao == 'bloquear':
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
                
                if acao == 'bloquear':
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
                
            except Exception as e:
                return ERRO
            
        except Exception as e:
            return ERRO
        finally:
            if browser:
                try:
                    time.sleep(2)
                    browser.close()
                except:
                    pass


if __name__ == '__main__':
    if len(sys.argv) > 1:
        email = sys.argv[1]
    else:
        print("USO: python rpa_saw.py <email_usuario> [bloquear|desbloquear]")
        sys.exit(1)

    acao = sys.argv[2].lower() if len(sys.argv) > 2 else 'bloquear'
    resultado = executar_saw_automatico(email, acao)
    sys.exit(resultado)
