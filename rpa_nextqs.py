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

# ZenRows Scraping Browser: resolve o desafio Cloudflare Turnstile no IP deles.
# Reusa as mesmas credenciais do GIU (mesma conta ZenRows).
ZENROWS_API_KEY = os.getenv('ZENROWS_API_KEY', '').strip()
ZENROWS_BROWSER_WSS = os.getenv('ZENROWS_BROWSER_WSS', 'wss://browser.zenrows.com').strip()
ZENROWS_PROXY_REGION = os.getenv('ZENROWS_PROXY_REGION', 'sa').strip()


def _normalizar_ttl(valor):
    valor = (valor or "").strip().lower()
    if not valor:
        return ""
    if valor.endswith("m") or valor.endswith("s"):
        return valor
    if valor.isdigit():
        seg = int(valor)
        return f"{seg // 60}m" if seg % 60 == 0 else f"{seg}s"
    return valor


ZENROWS_SESSION_TTL = _normalizar_ttl(os.getenv('ZENROWS_SESSION_TTL', '10m'))


def _abrir_browser(p):
    """Abre o navegador. Se ZENROWS_API_KEY estiver definido, conecta ao
    Scraping Browser do ZenRows via CDP (resolve o Turnstile no IP deles);
    caso contrario, lanca o Chromium local."""
    if ZENROWS_API_KEY:
        params = [f"apikey={ZENROWS_API_KEY}"]
        if ZENROWS_PROXY_REGION and ZENROWS_PROXY_REGION.lower() != 'global':
            params.append(f"proxy_region={ZENROWS_PROXY_REGION}")
        if ZENROWS_SESSION_TTL:
            params.append(f"session_ttl={ZENROWS_SESSION_TTL}")
        base = ZENROWS_BROWSER_WSS.split('?', 1)[0]
        url = base + '?' + '&'.join(params)
        browser = p.chromium.connect_over_cdp(url, timeout=120000)
        return browser, True

    browser = p.chromium.launch(
        channel="chrome", headless=False, args=["--window-size=1200,800"]
    )
    return browser, False

SUCESSO = 0
ERRO = 1
JA_INATIVO = 2
NAO_ENCONTRADO = 3
ATIVO = 4
INATIVO = 5


def consultar_status_nextqs(email_usuario):
    """Consulta o status no NextQS via RPA, sem alterar nada.

    Retorna ("ativo"|"inativo", None), (3, None) se não encontrado, ou
    ("erro", None) em falha — no mesmo formato dos outros consultores do painel.
    """
    codigo = executar_nextqs_automatico(email_usuario, apenas_consultar=True)
    if codigo == ATIVO:
        return "ativo", None
    if codigo == INATIVO:
        return "inativo", None
    if codigo == NAO_ENCONTRADO:
        return 3, None
    return "erro", None


def executar_nextqs_automatico(email_usuario, apenas_consultar=False):
    if not NEXTQS_USERNAME or not NEXTQS_PASSWORD:
        return ERRO
    
    with sync_playwright() as p:
        browser, usou_zenrows = _abrir_browser(p)
        if usou_zenrows:
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
        else:
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
            
            # Com o ZenRows o Turnstile ja e resolvido no lado deles; damos
            # uma janela curta para o widget confirmar antes de enviar o login.
            # Sem ZenRows (fallback local), esta espera dificilmente basta.
            for _ in range(15):
                try:
                    if page.locator("[data-turnstile-callback-success='true']").count() > 0:
                        break
                    if page.locator("text=Sucesso").count() > 0:
                        break
                except Exception:
                    pass
                time.sleep(1)
            time.sleep(1)
            
            page.click("button#submitLoginBtn")
            time.sleep(5)
            
            try:
                page.wait_for_load_state("networkidle", timeout=60000)
            except Exception:
                time.sleep(5)

            # Se ainda estamos na tela de login, o desafio Cloudflare nao passou
            # (ou credenciais recusadas). Sem isso, o fluxo seguiria e reportaria
            # "usuario nao encontrado", mascarando a real causa.
            try:
                url_pos = (page.url or "").lower()
                corpo_pos = (page.content() or "").lower()
            except Exception:
                url_pos, corpo_pos = "", ""
            if "login" in url_pos and ("turnstile" in corpo_pos or "cf-chl" in corpo_pos or "loginform-password" in corpo_pos):
                try:
                    page.screenshot(path="nextqs_debug_login.png", full_page=True)
                except Exception:
                    pass
                print("[NextQS] Login nao concluido (Cloudflare ou credenciais). Verifique ZENROWS_API_KEY.", file=sys.stderr)
                return ERRO
            
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

            if apenas_consultar:
                return ATIVO if esta_ativo else INATIVO

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
            print(f"[NextQS] Falha: {e}", file=sys.stderr)
            return ERRO
        finally:
            time.sleep(1)
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
