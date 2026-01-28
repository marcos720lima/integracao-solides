"""RPA GIU Unimed - Desativa usuarios no GIU"""

import sys
import time
import os
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


def executar_giu_automatico(cpf_usuario):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--window-size=600,400", "--window-position=3000,3000"]
        )
        page = browser.new_page()
        
        try:
            page.goto(f"{GIU_URL}/login", timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            page.fill("input[placeholder='Insira o CPF ou CNPJ']", GIU_USERNAME)
            time.sleep(0.5)
            page.fill("input[type='password'][placeholder='Insira a senha']", GIU_PASSWORD)
            time.sleep(0.5)
            page.click("button.unicomp-botao.primario")
            time.sleep(5)
            
            page.goto("https://giu.unimed.coop.br/gerenciarUsuarios", timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(3)
            
            campo_busca = page.locator("input[placeholder*='Buscar Nome']")
            campo_busca.fill(cpf_usuario)
            time.sleep(1)
            page.click("button.fonte-secundaria.texto")
            time.sleep(3)
            
            try:
                icone_editar = page.locator("div.icone-acao.habilitado")
                if icone_editar.count() == 0:
                    return NAO_ENCONTRADO
            except Exception:
                return NAO_ENCONTRADO
            
            page.click("div.icone-acao.habilitado")
            time.sleep(3)
            
            try:
                status_texto = page.locator("span.fonte-secundaria.texto.label-campo").first
                status_atual = status_texto.inner_text().strip().upper()
                
                if "INATIVA" in status_atual or "INATIVO" in status_atual:
                    return JA_INATIVO
            except Exception:
                pass
            
            try:
                page.click("span.slider.round")
            except Exception:
                try:
                    page.click("label.switch")
                except Exception:
                    page.click("input[type='checkbox']")
            
            time.sleep(2)
            
            page.click("button.unicomp-botao.primario:has-text('SALVAR')")
            time.sleep(3)
            
            try:
                page.click("button.unicomp-botao.primario:has-text('FECHAR')", timeout=5000)
                time.sleep(2)
            except Exception:
                pass
            
            return SUCESSO
            
        except Exception as e:
            return ERRO
        finally:
            time.sleep(2)
            browser.close()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        cpf = sys.argv[1]
    else:
        print("USO: python rpa_giu.py <cpf_usuario>")
        sys.exit(1)
    
    resultado = executar_giu_automatico(cpf)
    sys.exit(resultado)
