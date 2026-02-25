"""RPA Tasy EMR - Ativa/Inativa usuarios no Tasy"""

import sys
import time
import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

TASY_URL = os.getenv('TASY_URL', 'https://tasy.unimedoestedopara.coop.br')
TASY_USERNAME = os.getenv('TASY_USERNAME')
TASY_PASSWORD = os.getenv('TASY_PASSWORD')

SUCESSO = 0
ERRO = 1
JA_INATIVO = 2
NAO_ENCONTRADO = 3


def executar_tasy_automatico(nome_completo, nome_conta, acao='bloquear'):
    if acao not in ('bloquear', 'desbloquear'):
        return ERRO

    if not TASY_USERNAME or not TASY_PASSWORD:
        return ERRO
    
    nome_conta_comparacao = nome_conta.lower().replace('.', ' ')
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=True
        )
        page = browser.new_page()
        
        try:
            page.goto(f"{TASY_URL}/#/", timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(3)
            
            page.fill("input#loginUsername", TASY_USERNAME)
            time.sleep(0.5)
            
            page.fill("input#loginPassword", TASY_PASSWORD)
            time.sleep(0.5)
            
            page.click("input.btn-green.w-login-button")
            time.sleep(5)
            
            page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(3)
            
            try:
                admin_modulo = page.locator("span.w-feature-app__name:has-text('Administração do Sistema')")
                if admin_modulo.count() > 0:
                    admin_modulo.first.click()
                else:
                    page.click("a:has-text('Administração do Sistema')")
            except Exception:
                page.locator("text=Administração do Sistema").first.click()
            
            time.sleep(3)
            page.wait_for_load_state("networkidle", timeout=30000)
            
            time.sleep(2)
            
            try:
                usuarios_link = page.locator("text=Cadastro de usuários").first
                if usuarios_link.is_visible():
                    usuarios_link.click()
                else:
                    page.locator("span:has-text('Usuários')").first.click()
            except Exception:
                pass
            
            time.sleep(3)
            
            campo_nome = page.locator("input[name='NM_PESSOA'], input[placeholder='Nome']").first
            campo_nome.wait_for(state="visible", timeout=10000)
            campo_nome.fill(nome_completo)
            time.sleep(1)
            
            botao_filtrar = page.locator("button:has-text('Filtrar')").first
            botao_filtrar.click()
            time.sleep(3)
            
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(2)
            
            lista_vazia = page.locator("text=Esta lista está vazia").count()
            if lista_vazia > 0:
                return NAO_ENCONTRADO
            
            linhas = page.locator("div.ui-widget-content.slick-row").all()
            
            usuario_encontrado = False
            linha_usuario = None
            
            for linha in linhas:
                try:
                    texto_linha = linha.inner_text().lower()
                    nome_partes = nome_conta_comparacao.split()
                    
                    if all(parte in texto_linha for parte in nome_partes):
                        usuario_encontrado = True
                        linha_usuario = linha
                        break
                except Exception:
                    continue
            
            if not usuario_encontrado:
                return NAO_ENCONTRADO
            
            try:
                checkbox = linha_usuario.locator("input[type='checkbox'], label.wcheckbox-inputlabel").first
                if checkbox.count() > 0:
                    checkbox.click()
                else:
                    linha_usuario.click()
            except Exception:
                linha_usuario.click()
            
            time.sleep(1)
            
            try:
                botao_ver = page.locator("span.handlebar-button-label:has-text('Ver')").first
                botao_ver.click()
            except Exception:
                try:
                    page.locator("button:has-text('Ver')").first.click()
                except Exception:
                    page.locator(".handlebar-button:has-text('Ver'), .ng-scope.handlebar-button:has-text('Ver')").first.click()
            
            time.sleep(3)
            
            page.wait_for_load_state("networkidle", timeout=15000)
            
            radio_ativo = page.locator("input[type='radio'][value='A'], label:has-text('Ativo') input[type='radio']").first
            radio_inativo = page.locator("input[type='radio'][value='I'], label:has-text('Inativo') input[type='radio']").first
            
            esta_ativo = False
            try:
                if radio_ativo.is_checked():
                    esta_ativo = True
                elif radio_inativo.is_checked():
                    esta_ativo = False
            except Exception:
                esta_ativo = True
            
            if acao == 'bloquear' and not esta_ativo:
                try:
                    inativo_selecionado = page.locator("label:has-text('Inativo').selected, input[type='radio']:checked + label:has-text('Inativo')").count()
                    if inativo_selecionado > 0:
                        page.locator("span:has-text('Cancelar'), button:has-text('Cancelar')").first.click()
                        time.sleep(2)
                        return JA_INATIVO
                except Exception:
                    pass
            if acao == 'desbloquear' and esta_ativo:
                try:
                    page.locator("span:has-text('Cancelar'), button:has-text('Cancelar')").first.click()
                except Exception:
                    pass
                time.sleep(2)
                return JA_INATIVO
            
            try:
                if acao == 'bloquear':
                    page.locator("label:has-text('Inativo')").first.click()
                else:
                    page.locator("label:has-text('Ativo')").first.click()
            except Exception:
                try:
                    if acao == 'bloquear':
                        radio_inativo.click()
                    else:
                        radio_ativo.click()
                except Exception:
                    page.click("text=Inativo" if acao == 'bloquear' else "text=Ativo")
            
            time.sleep(1)
            
            try:
                botao_salvar = page.locator("span.wbutton-text:has-text('Salvar')").first
                botao_salvar.click()
            except Exception:
                try:
                    page.locator("div.wbutton-container.btn-blue:has-text('Salvar')").first.click()
                except Exception:
                    page.locator("button:has-text('Salvar')").first.click()
            
            time.sleep(3)
            
            page.wait_for_load_state("networkidle", timeout=15000)
            
            return SUCESSO
            
        except Exception:
            return ERRO
        finally:
            time.sleep(2)
            try:
                browser.close()
            except Exception:
                pass


if __name__ == '__main__':
    acao = 'bloquear'
    if len(sys.argv) >= 4:
        nome_completo = sys.argv[1]
        nome_conta = sys.argv[2]
        acao = sys.argv[3].lower()
    elif len(sys.argv) == 3:
        email = sys.argv[1]
        nome_conta = email.split('@')[0]
        nome_completo = nome_conta.replace('.', ' ').title()
        acao = sys.argv[2].lower()
    elif len(sys.argv) == 2:
        email = sys.argv[1]
        nome_conta = email.split('@')[0]
        nome_completo = nome_conta.replace('.', ' ').title()
    else:
        print("USO: python rpa_tasy.py <nome_completo> <nome_conta> [bloquear|desbloquear]")
        print("  ou: python rpa_tasy.py <email> [bloquear|desbloquear]")
        sys.exit(1)
    
    resultado = executar_tasy_automatico(nome_completo, nome_conta, acao)
    sys.exit(resultado)
