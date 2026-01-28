"""RPA GED Bye Bye Paper - Bloqueia usuarios no GED"""

import sys
import time
import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

GED_URL = os.getenv('GED_URL', 'https://app.gedbyebyepaper.com.br')
GED_CONTA = os.getenv('GED_CONTA')
GED_USERNAME = os.getenv('GED_USERNAME')
GED_PASSWORD = os.getenv('GED_PASSWORD')

SUCESSO = 0
ERRO = 1
JA_INATIVO = 2
NAO_ENCONTRADO = 3


def executar_ged_automatico(email_usuario):
    nome_busca = email_usuario.split('@')[0].split('.')[0]
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--window-size=600,400", "--window-position=3000,3000"]
        )
        page = browser.new_page()
        
        try:
            page.goto(GED_URL, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            page.fill("input[name='conta']", GED_CONTA)
            time.sleep(0.3)
            page.fill("input[name='usuario']", GED_USERNAME)
            time.sleep(0.3)
            page.fill("input[name='senha']", GED_PASSWORD)
            time.sleep(0.3)
            page.click("input.enviar")
            time.sleep(3)
            
            page.goto(f"{GED_URL}/idocs_main.php?seta_html=idocs_usuario_cons.php", timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            campo_busca = None
            seletores_busca = [
                "input[name='trecho']",
                "input.post[name='trecho']",
                "input[class*='post']",
                "form input[type='text']"
            ]
            
            for seletor in seletores_busca:
                try:
                    elemento = page.locator(seletor).first
                    if elemento.is_visible():
                        campo_busca = elemento
                        break
                except:
                    continue
            
            if campo_busca:
                campo_busca.fill(nome_busca)
            else:
                page.locator("input[type='text']").first.fill(nome_busca)
            
            time.sleep(0.5)
            page.click("button.btn.btn-success:has-text('Pesquisar')")
            time.sleep(3)
            
            linhas = page.locator("table.table-striped.table-bordered.table-hover tbody tr").all()
            usuario_encontrado = False
            link_editar = None
            
            for linha in linhas:
                try:
                    texto_linha = linha.inner_text()
                    
                    if email_usuario.lower() in texto_linha.lower():
                        link = linha.locator("a[href*='idocs_usuario_manu']").first
                        if link.count() > 0:
                            link_editar = link.get_attribute("href")
                            usuario_encontrado = True
                            break
                        else:
                            img_editar = linha.locator("img[alt='Editar']").first
                            if img_editar.count() > 0:
                                img_editar.click()
                                usuario_encontrado = True
                                break
                except:
                    continue
            
            if not usuario_encontrado:
                return NAO_ENCONTRADO
            
            if link_editar:
                if not link_editar.startswith('http'):
                    link_editar = f"{GED_URL}/{link_editar}"
                page.goto(link_editar, timeout=30000)
                time.sleep(2)
            
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            status_atual = None
            try:
                status_element = page.locator("span.genmed:has-text('BLOQUEADO'), span.genmed:has-text('ATIVO')").first
                if status_element.count() > 0:
                    status_atual = status_element.inner_text().strip()
            except:
                pass
            
            if status_atual and 'BLOQUEADO' in status_atual.upper():
                return JA_INATIVO
            
            page.click("button.btn.btn-yellow")
            time.sleep(2)
            
            page.select_option("select[name='cp5']", "BLOQUEADO")
            time.sleep(1)
            
            page.click("button.btn.btn-success:has-text('Confirmar')")
            time.sleep(3)
            
            return SUCESSO
            
        except Exception as e:
            return ERRO
        finally:
            time.sleep(2)
            browser.close()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        email = sys.argv[1]
    else:
        print("USO: python rpa_ged.py <email_usuario>")
        sys.exit(1)
    
    resultado = executar_ged_automatico(email)
    sys.exit(resultado)
