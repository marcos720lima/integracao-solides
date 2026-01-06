"""
RPA GIU - Desativa usuarios no GIU Unimed

Codigos de saida:
- 0 = Desativado com sucesso
- 1 = Erro
- 2 = Ja estava inativo
- 3 = Nao encontrado (nao possui acesso)
"""

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
    print("=" * 60)
    print("AUTOMATIZANDO GIU - Unimed")
    print("=" * 60)
    print(f"CPF: {cpf_usuario}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--window-size=600,400", "--window-position=3000,3000"]
        )
        page = browser.new_page()
        
        try:
            print("PASSO 1: Fazendo login...")
            page.goto(f"{GIU_URL}/login", timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            page.fill("input[placeholder='Insira o CPF ou CNPJ']", GIU_USERNAME)
            time.sleep(0.5)
            page.fill("input[type='password'][placeholder='Insira a senha']", GIU_PASSWORD)
            time.sleep(0.5)
            page.click("button.unicomp-botao.primario")
            print("   Login realizado!")
            time.sleep(5)
            
            print("PASSO 2: Acessando Gerenciar Usuarios...")
            page.goto("https://giu.unimed.coop.br/gerenciarUsuarios", timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(3)
            
            print(f"PASSO 3: Buscando usuario: {cpf_usuario}")
            campo_busca = page.locator("input[placeholder*='Buscar Nome']")
            campo_busca.fill(cpf_usuario)
            time.sleep(1)
            page.click("button.fonte-secundaria.texto")
            time.sleep(3)
            
            try:
                icone_editar = page.locator("div.icone-acao.habilitado")
                if icone_editar.count() == 0:
                    print("   Usuario nao encontrado no GIU!")
                    print("STATUS: NAO_ENCONTRADO")
                    return NAO_ENCONTRADO
            except Exception:
                print("   Usuario nao encontrado no GIU!")
                print("STATUS: NAO_ENCONTRADO")
                return NAO_ENCONTRADO
            
            print("PASSO 4: Abrindo edicao...")
            page.click("div.icone-acao.habilitado")
            time.sleep(3)
            
            print("PASSO 5: Verificando status atual...")
            try:
                status_texto = page.locator("span.fonte-secundaria.texto.label-campo").first
                status_atual = status_texto.inner_text().strip().upper()
                print(f"   Status atual: {status_atual}")
                
                if "INATIVA" in status_atual or "INATIVO" in status_atual:
                    print("   Usuario ja esta INATIVO!")
                    print("STATUS: JA_INATIVO")
                    return JA_INATIVO
            except Exception:
                pass
            
            print("PASSO 6: Alterando para INATIVA...")
            try:
                page.click("span.slider.round")
            except Exception:
                try:
                    page.click("label.switch")
                except Exception:
                    page.click("input[type='checkbox']")
            
            time.sleep(2)
            
            print("PASSO 7: Salvando...")
            page.click("button.unicomp-botao.primario:has-text('SALVAR')")
            time.sleep(3)
            
            print("PASSO 8: Fechando...")
            try:
                page.click("button.unicomp-botao.primario:has-text('FECHAR')", timeout=5000)
                time.sleep(2)
            except Exception:
                pass
            
            print("=" * 60)
            print(f"GIU: Usuario {cpf_usuario} desativado!")
            print("=" * 60)
            print("STATUS: SUCESSO")
            return SUCESSO
            
        except Exception as e:
            print(f"Erro no GIU: {str(e)}")
            print("STATUS: ERRO")
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
