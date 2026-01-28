"""RPA NextQS Manager - Inativa usuarios no NextQS"""

import sys
import time
import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

NEXTQS_URL = os.getenv('NEXTQS_URL', 'https://manager.nextqs.com')
NEXTQS_USERNAME = os.getenv('NEXTQS_USERNAME')
NEXTQS_PASSWORD = os.getenv('NEXTQS_PASSWORD')

SUCESSO = 0
ERRO = 1
JA_INATIVO = 2
NAO_ENCONTRADO = 3


def executar_nextqs_automatico(email_usuario):
    if not NEXTQS_USERNAME or not NEXTQS_PASSWORD:
        return ERRO
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--window-size=1200,800"]
        )
        page = browser.new_page()
        
        try:
            page.goto(f"{NEXTQS_URL}/login.html", timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            campo_usuario = page.locator("input#loginform-username")
            campo_usuario.fill(NEXTQS_USERNAME)
            time.sleep(0.5)
            
            campo_usuario.press("Enter")
            time.sleep(2)
            
            page.wait_for_selector("input#loginform-password", state="visible", timeout=10000)
            page.fill("input#loginform-password", NEXTQS_PASSWORD)
            time.sleep(1)
            
            turnstile_resolvido = False
            tentativas = 0
            max_tentativas = 45
            
            while not turnstile_resolvido and tentativas < max_tentativas:
                try:
                    if tentativas == 5:
                        try:
                            widget = page.locator("div.cf-turnstile, iframe[src*='turnstile']").first
                            if widget.is_visible():
                                widget.click()
                        except Exception:
                            pass
                    
                    sucesso_texto = page.locator("text=Sucesso").count()
                    if sucesso_texto > 0:
                        turnstile_resolvido = True
                        break
                    
                    widget_success = page.locator("[data-turnstile-callback-success='true']").count()
                    if widget_success > 0:
                        turnstile_resolvido = True
                        break
                        
                except Exception:
                    pass
                
                tentativas += 1
                time.sleep(1)
            
            time.sleep(2)
            
            page.click("button#submitLoginBtn")
            time.sleep(5)
            
            try:
                page.wait_for_load_state("networkidle", timeout=60000)
            except Exception:
                time.sleep(5)
            
            page.goto(f"{NEXTQS_URL}/users.html", timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            campo_pesquisa = page.locator("input[type='search'][aria-controls='usersDataTable']")
            campo_pesquisa.wait_for(state="visible", timeout=10000)
            campo_pesquisa.fill(email_usuario)
            time.sleep(2)
            
            time.sleep(1)
            
            tabela = page.locator("table#usersDataTable tbody")
            linhas = tabela.locator("tr").all()
            
            usuario_encontrado = False
            botao_editar = None
            
            for linha in linhas:
                try:
                    texto_linha = linha.inner_text()
                    if email_usuario.lower() in texto_linha.lower():
                        usuario_encontrado = True
                        botao_editar = linha.locator("a.btn-primary").first
                        break
                except Exception:
                    continue
            
            try:
                sem_dados = page.locator("td.dataTables_empty")
                if sem_dados.count() > 0 and sem_dados.is_visible():
                    return NAO_ENCONTRADO
            except Exception:
                pass
            
            if not usuario_encontrado or not botao_editar:
                return NAO_ENCONTRADO
            
            botao_editar.click()
            time.sleep(2)
            page.wait_for_load_state("domcontentloaded")
            
            toggle_ativar = page.locator("input#swtActivated")
            toggle_ativar.wait_for(state="attached", timeout=10000)
            
            esta_ativo = toggle_ativar.is_checked()
            
            if not esta_ativo:
                return JA_INATIVO
            
            label_toggle = page.locator("label[for='swtActivated']")
            if label_toggle.count() > 0:
                label_toggle.click()
            else:
                toggle_ativar.click()
            time.sleep(1)
            
            page.click("button#btnUpdate")
            time.sleep(3)
            
            page.wait_for_load_state("networkidle", timeout=30000)
            
            return SUCESSO
            
        except Exception as e:
            return ERRO
        finally:
            time.sleep(2)
            try:
                browser.close()
            except Exception:
                pass


if __name__ == '__main__':
    if len(sys.argv) > 1:
        email = sys.argv[1]
    else:
        print("USO: python rpa_nextqs.py <email_usuario>")
        sys.exit(1)
    
    resultado = executar_nextqs_automatico(email)
    sys.exit(resultado)
