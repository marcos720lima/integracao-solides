"""RPA B+ Reembolso - Inativa usuarios no B+"""

import sys
import time
import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BPLUS_URL = os.getenv('BPLUS_URL', 'https://bplus.unimedoestedopara.coop.br')
BPLUS_USERNAME = os.getenv('BPLUS_USERNAME')
BPLUS_PASSWORD = os.getenv('BPLUS_PASSWORD')

SUCESSO = 0
ERRO = 1
JA_INATIVO = 2
NAO_ENCONTRADO = 3


def executar_bplus_automatico(email_usuario):
    nome_conta = email_usuario.split('@')[0]
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--window-size=600,400", "--window-position=3000,3000"]
        )
        page = browser.new_page()
        
        try:
            page.goto(f"{BPLUS_URL}/login", timeout=60000)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(2)
            
            page.fill("input#usuario", BPLUS_USERNAME)
            time.sleep(0.5)
            
            page.fill("input#senha", BPLUS_PASSWORD)
            time.sleep(0.5)
            
            page.click("button.btn-success[type='submit']")
            time.sleep(5)
            
            page.goto(f"{BPLUS_URL}/conf/usuarios", timeout=30000)
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            time.sleep(3)
            
            campo_busca = page.locator("input[type='text']").first
            if campo_busca.is_visible():
                campo_busca.fill(nome_conta)
                time.sleep(0.5)
                page.keyboard.press("Enter")
                time.sleep(3)
            else:
                page.fill("input.form-control", nome_conta)
                time.sleep(0.5)
                page.keyboard.press("Enter")
                time.sleep(3)
            
            checkboxes = page.locator("input.form-check-input[type='checkbox']").all()
            
            if not checkboxes:
                return NAO_ENCONTRADO
            
            tabela = page.locator("table tbody tr")
            usuario_encontrado = False
            checkbox_usuario = None
            
            linhas = tabela.all()
            for linha in linhas:
                texto_linha = linha.inner_text().lower()
                if nome_conta.lower() in texto_linha:
                    usuario_encontrado = True
                    checkbox_usuario = linha.locator("input.form-check-input[type='checkbox']")
                    break
            
            if not usuario_encontrado:
                return NAO_ENCONTRADO
            
            if checkbox_usuario and checkbox_usuario.is_visible():
                checkbox_usuario.click()
            else:
                page.locator("input.form-check-input[type='checkbox']").first.click()
            time.sleep(1)
            
            botao_inativar = page.locator("button:has-text('Inativar')")
            
            if not botao_inativar.is_visible():
                botao_ativar = page.locator("button:has-text('Ativar')")
                if botao_ativar.is_visible():
                    return JA_INATIVO
                else:
                    return ERRO
            
            botao_inativar.click()
            time.sleep(2)
            
            page.wait_for_selector("div.modal-body, div#theDialog-body", timeout=5000)
            time.sleep(1)
            
            botao_ok = page.locator("button.btn-danger:has-text('Ok')")
            if botao_ok.is_visible():
                botao_ok.click()
            else:
                page.click("button.btn-danger")
            
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
        print("USO: python rpa_bplus.py <email_usuario>")
        sys.exit(1)
    
    resultado = executar_bplus_automatico(email)
    sys.exit(resultado)
