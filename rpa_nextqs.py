"""
RPA NextQS - Inativa usuarios no NextQS Manager

Codigos de saida:
- 0 = Inativado com sucesso
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

NEXTQS_URL = os.getenv('NEXTQS_URL', 'https://manager.nextqs.com')
NEXTQS_USERNAME = os.getenv('NEXTQS_USERNAME')
NEXTQS_PASSWORD = os.getenv('NEXTQS_PASSWORD')

SUCESSO = 0
ERRO = 1
JA_INATIVO = 2
NAO_ENCONTRADO = 3


def executar_nextqs_automatico(email_usuario):
    print("=" * 60)
    print("AUTOMATIZANDO NEXTQS - Manager")
    print("=" * 60)
    print(f"Email: {email_usuario}")
    
    # Validar credenciais
    if not NEXTQS_USERNAME or not NEXTQS_PASSWORD:
        print("ERRO: Credenciais NEXTQS_USERNAME e/ou NEXTQS_PASSWORD não configuradas no .env")
        print("STATUS: ERRO")
        return ERRO
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--window-size=600,400", "--window-position=3000,3000"]
        )
        page = browser.new_page()
        
        try:
            # PASSO 1: Abrir página de login
            print("PASSO 1: Abrindo página de login...")
            page.goto(f"{NEXTQS_URL}/login.html", timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            # PASSO 2: Preencher email/usuario
            print("PASSO 2: Preenchendo usuário...")
            campo_usuario = page.locator("input#loginform-username")
            campo_usuario.fill(NEXTQS_USERNAME)
            time.sleep(0.5)
            
            # Pressionar Enter para aparecer campo de senha
            campo_usuario.press("Enter")
            time.sleep(1)
            
            # PASSO 3: Preencher senha
            print("PASSO 3: Preenchendo senha...")
            page.wait_for_selector("input#loginform-password", state="visible", timeout=10000)
            page.fill("input#loginform-password", NEXTQS_PASSWORD)
            time.sleep(0.5)
            
            # PASSO 4: Clicar em Começar
            print("PASSO 4: Clicando em Começar...")
            page.click("button#submitLoginBtn")
            time.sleep(3)
            
            # Aguardar redirecionamento/login completar
            page.wait_for_load_state("networkidle", timeout=30000)
            print("   Login realizado!")
            
            # PASSO 5: Navegar para página de usuários
            print("PASSO 5: Indo para página de usuários...")
            page.goto(f"{NEXTQS_URL}/users.html", timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            
            # PASSO 6: Pesquisar usuário pelo email
            print(f"PASSO 6: Pesquisando usuário: {email_usuario}")
            campo_pesquisa = page.locator("input[type='search'][aria-controls='usersDataTable']")
            campo_pesquisa.wait_for(state="visible", timeout=10000)
            campo_pesquisa.fill(email_usuario)
            time.sleep(2)  # Aguardar filtro da tabela
            
            # PASSO 7: Verificar se usuário foi encontrado
            print("PASSO 7: Verificando se usuário foi encontrado...")
            time.sleep(1)
            
            # Procurar linha na tabela que contenha o email
            tabela = page.locator("table#usersDataTable tbody")
            linhas = tabela.locator("tr").all()
            
            usuario_encontrado = False
            botao_editar = None
            
            for linha in linhas:
                try:
                    texto_linha = linha.inner_text()
                    if email_usuario.lower() in texto_linha.lower():
                        print("   Usuário encontrado na tabela!")
                        usuario_encontrado = True
                        # Procurar botão de editar (lápis azul) - é um link com classe btn-primary
                        botao_editar = linha.locator("a.btn-primary").first
                        break
                except Exception:
                    continue
            
            # Verificar também mensagem de "nenhum registro"
            try:
                sem_dados = page.locator("td.dataTables_empty")
                if sem_dados.count() > 0 and sem_dados.is_visible():
                    print("   Nenhum usuário encontrado (tabela vazia).")
                    print("STATUS: NAO_ENCONTRADO")
                    return NAO_ENCONTRADO
            except Exception:
                pass
            
            if not usuario_encontrado or not botao_editar:
                print("   Usuário não encontrado no NextQS!")
                print("STATUS: NAO_ENCONTRADO")
                return NAO_ENCONTRADO
            
            # PASSO 8: Clicar no botão de editar
            print("PASSO 8: Clicando no botão de editar...")
            botao_editar.click()
            time.sleep(2)
            page.wait_for_load_state("domcontentloaded")
            
            # PASSO 9: Verificar status atual do toggle "Ativar"
            print("PASSO 9: Verificando status atual...")
            toggle_ativar = page.locator("input#swtActivated")
            toggle_ativar.wait_for(state="attached", timeout=10000)
            
            esta_ativo = toggle_ativar.is_checked()
            
            if not esta_ativo:
                print("   Usuário já está INATIVO!")
                print("STATUS: JA_INATIVO")
                return JA_INATIVO
            
            print("   Usuário está ATIVO, desativando...")
            
            # PASSO 10: Desmarcar o toggle para inativar
            print("PASSO 10: Desmarcando toggle de ativação...")
            # Clicar no label do toggle (mais confiável que clicar no checkbox)
            label_toggle = page.locator("label[for='swtActivated']")
            if label_toggle.count() > 0:
                label_toggle.click()
            else:
                toggle_ativar.click()
            time.sleep(1)
            
            # PASSO 11: Clicar em Atualizar
            print("PASSO 11: Clicando em Atualizar...")
            page.click("button#btnUpdate")
            time.sleep(3)
            
            # Aguardar confirmação (pode ser redirecionamento ou mensagem)
            page.wait_for_load_state("networkidle", timeout=30000)
            
            print("=" * 60)
            print(f"NEXTQS: Usuário {email_usuario} inativado com sucesso!")
            print("=" * 60)
            print("STATUS: SUCESSO")
            return SUCESSO
            
        except Exception as e:
            print(f"Erro no NextQS: {str(e)}")
            print("STATUS: ERRO")
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
