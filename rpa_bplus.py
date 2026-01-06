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
    print("=" * 60)
    print("AUTOMATIZANDO B+ (Site de Reembolso)")
    print("=" * 60)
    print(f"Email: {email_usuario}")
    
    # Extrai nome de conta do email (ex: douglas.barreto)
    nome_conta = email_usuario.split('@')[0]
    print(f"Buscando por nome de conta: {nome_conta}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--window-size=600,400", "--window-position=3000,3000"]
        )
        page = browser.new_page()
        
        try:
            # PASSO 1: Login
            print("PASSO 1: Fazendo login...")
            page.goto(f"{BPLUS_URL}/login", timeout=60000)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(2)
            
            # Preencher usuário
            page.fill("input#usuario", BPLUS_USERNAME)
            time.sleep(0.5)
            
            # Preencher senha
            page.fill("input#senha", BPLUS_PASSWORD)
            time.sleep(0.5)
            
            # Clicar em Entrar
            page.click("button.btn-success[type='submit']")
            print("   Login realizado!")
            time.sleep(5)
            
            # PASSO 2: Navegar para página de usuários
            print("PASSO 2: Navegando para usuarios...")
            page.goto(f"{BPLUS_URL}/conf/usuarios", timeout=30000)
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            time.sleep(3)
            
            # PASSO 3: Buscar usuário pelo nome de conta
            print(f"PASSO 3: Buscando usuario: {nome_conta}")
            
            # Localizar campo de busca e digitar
            campo_busca = page.locator("input[type='text']").first
            if campo_busca.is_visible():
                campo_busca.fill(nome_conta)
                time.sleep(0.5)
                page.keyboard.press("Enter")
                time.sleep(3)
            else:
                # Tentar outro seletor
                page.fill("input.form-control", nome_conta)
                time.sleep(0.5)
                page.keyboard.press("Enter")
                time.sleep(3)
            
            # PASSO 4: Verificar se usuário foi encontrado
            print("PASSO 4: Verificando resultado da busca...")
            
            # Verificar se existe alguma linha na tabela
            checkboxes = page.locator("input.form-check-input[type='checkbox']").all()
            
            if not checkboxes:
                print("   Usuario nao encontrado no B+!")
                print("STATUS: NAO_ENCONTRADO")
                return NAO_ENCONTRADO
            
            # Verificar se o checkbox está na linha correta (com o nome de conta)
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
                print("   Usuario nao encontrado na tabela!")
                print("STATUS: NAO_ENCONTRADO")
                return NAO_ENCONTRADO
            
            # PASSO 5: Selecionar o checkbox do usuário
            print("PASSO 5: Selecionando usuario...")
            if checkbox_usuario and checkbox_usuario.is_visible():
                checkbox_usuario.click()
            else:
                # Tentar clicar no primeiro checkbox visível
                page.locator("input.form-check-input[type='checkbox']").first.click()
            time.sleep(1)
            
            # PASSO 6: Verificar se botão "Inativar" está visível
            print("PASSO 6: Verificando botao de inativar...")
            
            botao_inativar = page.locator("button:has-text('Inativar')")
            
            if not botao_inativar.is_visible():
                # Usuario pode já estar inativo - verificar se tem botão "Ativar"
                botao_ativar = page.locator("button:has-text('Ativar')")
                if botao_ativar.is_visible():
                    print("   Usuario ja esta INATIVO!")
                    print("STATUS: JA_INATIVO")
                    return JA_INATIVO
                else:
                    print("   Botao de inativar nao encontrado")
                    print("STATUS: ERRO")
                    return ERRO
            
            # PASSO 7: Clicar no botão Inativar
            print("PASSO 7: Clicando em Inativar...")
            botao_inativar.click()
            time.sleep(2)
            
            # PASSO 8: Confirmar no modal
            print("PASSO 8: Confirmando inativacao no modal...")
            
            # Aguardar modal aparecer
            page.wait_for_selector("div.modal-body, div#theDialog-body", timeout=5000)
            time.sleep(1)
            
            # Clicar no botão OK (btn-danger)
            botao_ok = page.locator("button.btn-danger:has-text('Ok')")
            if botao_ok.is_visible():
                botao_ok.click()
            else:
                # Tentar outro seletor
                page.click("button.btn-danger")
            
            time.sleep(3)
            
            print("=" * 60)
            print(f"B+: Usuario {nome_conta} inativado!")
            print("=" * 60)
            print("STATUS: SUCESSO")
            return SUCESSO
                
        except Exception as e:
            print(f"Erro no B+: {str(e)}")
            print("STATUS: ERRO")
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

