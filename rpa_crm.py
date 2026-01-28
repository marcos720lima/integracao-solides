"""RPA CRM JMJ - Desativa usuarios no CRM"""

import sys
import time
import os
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


def executar_crm_automatico(email_usuario):
    nome_usuario = email_usuario.split('@')[0].replace('.', ' ').lower()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--window-size=600,400", "--window-position=3000,3000"]
        )
        page = browser.new_page()
        
        try:
            page.goto(f"{CRM_URL}/#/authenticate", timeout=60000)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(3)
            
            page.click("input[ng-model='credentials.username']")
            page.fill("input[ng-model='credentials.username']", "")
            page.type("input[ng-model='credentials.username']", CRM_USERNAME, delay=100)
            
            page.click("input[name='senha']")
            page.fill("input[name='senha']", "")
            page.type("input[name='senha']", CRM_PASSWORD, delay=100)
            
            page.evaluate("angular.element(document.querySelector(\"input[ng-model='credentials.username']\")).scope().$apply()")
            page.evaluate("angular.element(document.querySelector(\"input[name='senha']\")).scope().$apply()")
            
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
                except:
                    continue
            
            if not usuario_divs:
                try:
                    primeira_linha = page.locator("tr.ng-scope, div.usuario-item, div[ng-repeat]").first
                    if primeira_linha.is_visible():
                        usuario_divs.append((0, primeira_linha))
                except:
                    pass
            
            if not usuario_divs:
                return NAO_ENCONTRADO
            
            sucesso = False
            for i, div in usuario_divs:
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
                                    if text and 'editar' in text.lower():
                                        elem.click()
                                        time.sleep(5)
                                        
                                        if page.locator("jmj-toggle").count() > 0 or page.locator("strong:has-text('Ativo')").count() > 0:
                                            sucesso = True
                                            break
                            except:
                                continue
                        if sucesso:
                            break
                    if sucesso:
                        break
                except:
                    continue
            
            if not sucesso:
                return NAO_ENCONTRADO
            
            try:
                toggle = page.locator("jmj-toggle button, button[tabindex='-1']").first
                toggle_class = toggle.get_attribute("class") or ""
                if "off" in toggle_class.lower() or "inactive" in toggle_class.lower():
                    return JA_INATIVO
            except:
                pass
            
            try:
                page.click("button[ng-click='ingDisabled ? ngModel = !ngModel : null']")
            except:
                try:
                    page.click("jmj-toggle button")
                except:
                    page.click("button[tabindex='-1']")
            
            time.sleep(2)
            
            page.click("button.btn.btn-flat.btn-tumblr:has-text('Salvar')")
            time.sleep(3)
            
            return SUCESSO
                
        except Exception as e:
            return ERRO
        finally:
            browser.close()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        email = sys.argv[1]
    else:
        print("USO: python rpa_crm.py <email_usuario>")
        sys.exit(1)
    
    resultado = executar_crm_automatico(email)
    sys.exit(resultado)
