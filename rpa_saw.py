"""
RPA SAW - Desativa usuarios no SAW

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

SAW_URL = os.getenv('SAW_URL', 'https://saw.trixti.com.br/saw')
SAW_USERNAME = os.getenv('SAW_USERNAME')
SAW_PASSWORD = os.getenv('SAW_PASSWORD')

SUCESSO = 0
ERRO = 1
JA_INATIVO = 2
NAO_ENCONTRADO = 3

def executar_saw_automatico(email_usuario):
    print("=" * 60)
    print("AUTOMATIZANDO SAW")
    print("=" * 60)
    print(f"Email: {email_usuario}")
    
    browser = None
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                channel="chrome", 
                headless=False,
                args=["--window-size=600,400", "--window-position=3000,3000"]
            )
            page = browser.new_page()
            
            try:
                print("PASSO 1: Fazendo login...")
                page.goto(f"{SAW_URL}/Logar.do?method=abrirSAW", timeout=60000)
                page.fill("input[name='j_username']", SAW_USERNAME)
                page.fill("input[name='j_password']", SAW_PASSWORD)
                page.click("input#submitForm")
                page.wait_for_load_state("domcontentloaded", timeout=30000)
                print("   Login realizado!")
                time.sleep(2)
                
                print("PASSO 2: Navegando para usuarios...")
                page.goto(f"{SAW_URL}/ManterUsuario.do?comando=abrirTelaInicialDeUsuario", timeout=60000)
                page.wait_for_load_state("domcontentloaded", timeout=30000)
                time.sleep(2)
                
                print(f"PASSO 3: Buscando usuario: {email_usuario}")
                campo = "input[name='filtroDePesquisaDeUsuarios.usuario.email']"
                page.fill(campo, email_usuario)
                page.press(campo, "Enter")
                time.sleep(3)
                
                icone_desativar = page.locator("img[src*='desativarUsuario']")
                icone_ativar = page.locator("img[src*='ativarUsuario']")
                
                if icone_desativar.count() == 0 and icone_ativar.count() == 0:
                    print("   Usuario nao encontrado no SAW!")
                    print("STATUS: NAO_ENCONTRADO")
                    return NAO_ENCONTRADO
                
                if icone_desativar.count() == 0 and icone_ativar.count() > 0:
                    print("   Usuario ja esta INATIVO!")
                    print("STATUS: JA_INATIVO")
                    return JA_INATIVO
                
                print("PASSO 4: Clicando em desativar...")
                
                # Sobrescrever confirm() para sempre retornar true
                page.evaluate("window.confirm = () => true;")
                
                try:
                    icone_desativar.first.click()
                except:
                    try:
                        page.click("img[src*='desativarUsuario']")
                    except:
                        page.click("img[title*='Desativar'], img[alt*='Desativar']")
                
                print("   Aguardando processamento...")
                time.sleep(3)
                
                # Verificar se desativou (recarregar e buscar novamente)
                page.reload()
                time.sleep(2)
                
                page.fill(campo, email_usuario)
                page.press(campo, "Enter")
                time.sleep(3)
                
                icone_ativar_depois = page.locator("img[src*='ativarUsuario']")
                icone_desativar_depois = page.locator("img[src*='desativarUsuario']")
                
                if icone_ativar_depois.count() > 0 and icone_desativar_depois.count() == 0:
                    print("=" * 60)
                    print(f"SAW: Usuario {email_usuario} desativado!")
                    print("=" * 60)
                    print("STATUS: SUCESSO")
                    return SUCESSO
                elif icone_desativar_depois.count() > 0:
                    print("   Falha - usuario ainda ativo")
                    print("STATUS: ERRO")
                    return ERRO
                else:
                    print("=" * 60)
                    print(f"SAW: Usuario {email_usuario} provavelmente desativado!")
                    print("=" * 60)
                    print("STATUS: SUCESSO")
                    return SUCESSO
                
            except Exception as e:
                print(f"Erro no SAW: {str(e)}")
                print("STATUS: ERRO")
                return ERRO
            
        except Exception as e:
            print(f"Erro geral: {str(e)}")
            print("STATUS: ERRO")
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
        print("USO: python rpa_saw.py <email_usuario>")
        sys.exit(1)
    
    resultado = executar_saw_automatico(email)
    sys.exit(resultado)
