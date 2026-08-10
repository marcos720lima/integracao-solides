import os
from functools import lru_cache
from datetime import datetime
from PIL import Image
import streamlit as st
import pandas as pd

from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Integração Solides - Painel", layout="wide")

DATA_CSV = os.path.join(os.path.dirname(__file__), 'data', 'desligamentos_historico.csv')
LOGO_PATH = os.path.join(os.path.dirname(__file__), 'data', 'logo_unimed.png')
PRIMARY_COLOR = '#00995d'
TI_DESCRIPTION_KEYWORD = os.getenv('TI_DESCRIPTION_KEYWORD', 'TI').lower()


def _normalize_text(value):
    return (str(value or '')).strip().lower()


def apply_styles():
    st.markdown(
        f"""
        <style>
            .stApp {{
                background: linear-gradient(180deg, #f6fbf8 0%, #ffffff 18%, #ffffff 100%);
                color: #1f2937;
            }}

            [data-testid="stSidebar"] {{
                background: #f7faf8;
                border-right: 1px solid rgba(0, 153, 93, 0.15);
            }}

            .block-container {{
                padding-top: 1.2rem;
                padding-bottom: 2rem;
                max-width: 1180px;
            }}

            .hero-card {{
                background: white;
                border: 1px solid rgba(0, 153, 93, 0.12);
                box-shadow: 0 12px 34px rgba(0, 0, 0, 0.06);
                border-radius: 22px;
                padding: 1.2rem 1.4rem;
                margin-bottom: 1rem;
            }}

            .hero-title {{
                color: {PRIMARY_COLOR};
                font-weight: 800;
                font-size: 2rem;
                line-height: 1.1;
                margin-bottom: 0.25rem;
            }}

            .hero-subtitle {{
                color: #4b5563;
                font-size: 0.98rem;
                margin-bottom: 0;
            }}

            .accent-bar {{
                height: 6px;
                background: {PRIMARY_COLOR};
                border-radius: 999px;
                margin: 0.2rem 0 1rem 0;
            }}

            .login-badge {{
                display: inline-block;
                padding: 0.35rem 0.8rem;
                border-radius: 999px;
                background: rgba(0, 153, 93, 0.1);
                color: {PRIMARY_COLOR};
                font-weight: 700;
                font-size: 0.85rem;
                margin-bottom: 0.8rem;
            }}

            .login-form-title {{
                color: #111827;
                font-weight: 700;
                font-size: 1.1rem;
                margin-bottom: 0.8rem;
            }}

            .field-hint {{
                color: #4b5563;
                font-size: 0.84rem;
                margin-top: -0.3rem;
                margin-bottom: 0.75rem;
            }}

            .section-card {{
                background: white;
                border: 1px solid rgba(0, 153, 93, 0.12);
                box-shadow: 0 10px 28px rgba(0, 0, 0, 0.05);
                border-radius: 20px;
                padding: 1.1rem 1.2rem;
                margin: 1rem 0 1.2rem 0;
            }}

            .login-shell {{
                max-width: 380px;
                margin: 0 auto;
            }}

            .login-shell [data-testid="stForm"] {{
                background: #ffffff;
                border: 1px solid rgba(0, 153, 93, 0.16);
                border-radius: 20px;
                padding: 1.1rem 1.1rem 0.6rem 1.1rem;
                box-shadow: 0 14px 35px rgba(0, 0, 0, 0.06);
            }}

            .login-shell [data-testid="stForm"] button[kind="primary"],
            .login-shell button[kind="primary"] {{
                background: #00995d !important;
                border-color: #00995d !important;
                color: #2f2f2f !important;
                width: 100%;
                border-radius: 12px;
                font-weight: 700;
                padding: 0.45rem 0.8rem;
                min-height: 2.45rem;
            }}

            .login-shell [data-testid="stForm"] button[kind="primary"]:hover,
            .login-shell button[kind="primary"]:hover {{
                background: #007a45 !important;
                border-color: #007a45 !important;
                color: #ffffff !important;
            }}

            .login-shell [data-testid="stForm"] input,
            .login-shell input[type="text"],
            .login-shell input[type="password"],
            .login-shell textarea {{
                background: #ffffff !important;
                color: #111827 !important;
                border-radius: 10px !important;
                border: 1px solid #d1d5db !important;
                padding: 0.42rem 0.7rem !important;
                font-size: 0.95rem !important;
                min-height: 2.2rem !important;
            }}

            .login-shell input::placeholder {{
                color: #64748b !important;
            }}

            div[data-baseweb="input"] > div,
            div[data-baseweb="textarea"] > div {{
                background: #ffffff !important;
                color: #111827 !important;
                border-color: #cbd5e1 !important;
            }}

            label,
            .stTextInput label,
            .stTextArea label,
            .stSelectbox label,
            .stNumberInput label,
            .stCheckbox label,
            .stRadio label {{
                color: #111827 !important;
                font-weight: 600 !important;
            }}

            .stCaption, p, span, div {{
                color: #374151;
            }}

            div[data-testid="stSidebar"] * {{
                color: #1f2937;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


@lru_cache(maxsize=1)
def _get_ad_config():
    return {
        'ad_url': os.getenv('AD_URL', ''),
        'base_dn': os.getenv('BASE_DN', ''),
        'bind_user': os.getenv('AD_USER', ''),
        'bind_pass': os.getenv('AD_PASS', ''),
    }


def authenticate_ti_user(username: str, password: str):
    """Valida credenciais no AD e confirma se a descrição contém TI."""
    if not username or not password:
        return False, 'Informe usuário e senha do domínio.'

    try:
        from ldap3 import ALL, Connection, Server
    except Exception as exc:
        return False, f'ldap3 indisponível: {exc}'

    config = _get_ad_config()
    if not config['ad_url'] or not config['base_dn']:
        return False, 'AD_URL ou BASE_DN não configurados no .env.'

    try:
        server = Server(config['ad_url'], get_info=ALL, use_ssl=True)
        conn_login = Connection(server, user=username, password=password, auto_bind=True)
        conn_login.unbind()

        conn_search = Connection(
            server,
            user=config['bind_user'],
            password=config['bind_pass'],
            auto_bind=True,
        )

        username_escaped = username.replace('\\', '\\\\')
        search_filter = (
            f"(|(sAMAccountName={username_escaped})(userPrincipalName={username_escaped})(mail={username_escaped}))"
        )
        conn_search.search(
            search_base=config['base_dn'],
            search_filter=search_filter,
            attributes=['description', 'displayName', 'mail', 'sAMAccountName'],
        )

        if not conn_search.entries:
            conn_search.unbind()
            return False, 'Usuário autenticou, mas não foi encontrado no AD.'

        entry = conn_search.entries[0]
        description_attr = getattr(entry, 'description', None)
        description = _normalize_text(description_attr.value if description_attr else '')
        display_attr = getattr(entry, 'displayName', None)
        display_name = display_attr.value if display_attr else username
        conn_search.unbind()

        if TI_DESCRIPTION_KEYWORD and TI_DESCRIPTION_KEYWORD not in description:
            return False, f'Acesso negado para {display_name}: descrição sem o marcador de TI.'

        return True, f'Autenticado como {display_name}.'
    except Exception as exc:
        return False, f'Falha no login do AD: {exc}'


def centered_logo():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if os.path.exists(LOGO_PATH):
            try:
                logo_img = Image.open(LOGO_PATH)
                st.image(logo_img, width=340)
            except Exception:
                st.markdown(
                    f"<div style='text-align:center; color:{PRIMARY_COLOR}; font-weight:800; font-size:1.4rem;'>Unimed Oeste do Pará</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                f"<div style='text-align:center; color:{PRIMARY_COLOR}; font-weight:800; font-size:1.4rem;'>Unimed Oeste do Pará</div>",
                unsafe_allow_html=True,
            )


def hero_section():
    st.markdown(
        f"""
        <div class="hero-card" style="text-align:center;">
            <div class="hero-title">Integração Solides</div>
            <div class="accent-bar"></div>
            <p class="hero-subtitle">Painel centralizado para consulta de desligamentos e inativação manual.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


apply_styles()

st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)
centered_logo()
hero_section()

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'auth_message' not in st.session_state:
    st.session_state.auth_message = ''


if not st.session_state.authenticated:
    left, center, right = st.columns([1, 2.2, 1])
    with center:
        st.markdown("<div class='login-shell'>", unsafe_allow_html=True)
        with st.form('login_ad'):
            login_usuario = st.text_input('Usuário do domínio', placeholder='usuario@empresa.com ou DOMINIO\\usuario')
            login_senha = st.text_input('Senha', type='password')
            login_submit = st.form_submit_button('Entrar')
        st.markdown("</div>", unsafe_allow_html=True)

        if login_submit:
            ok, msg = authenticate_ti_user(login_usuario, login_senha)
            if ok:
                st.session_state.authenticated = True
                st.session_state.auth_message = msg
                if hasattr(st, 'rerun'):
                    st.rerun()
                else:
                    st.experimental_rerun()
            else:
                st.session_state.auth_message = msg

        if st.session_state.auth_message:
            st.error(st.session_state.auth_message)

    st.stop()

st.sidebar.markdown(
    f"""
    <div style="padding:1rem 0.9rem 0.8rem 0.9rem; border-radius:18px; background: rgba(0,153,93,0.08); border:1px solid rgba(0,153,93,0.15);">
        <div style="color:{PRIMARY_COLOR}; font-weight:800; font-size:1rem;">Sessão ativa</div>
        <div style="color:#374151; font-size:0.88rem; margin-top:0.35rem;">{st.session_state.auth_message or 'Acesso liberado'}</div>
    </div>
    """,
    unsafe_allow_html=True,
)
if st.sidebar.button('Sair'):
    st.session_state.authenticated = False
    st.session_state.auth_message = ''
    if hasattr(st, 'rerun'):
        st.rerun()
    else:
        st.experimental_rerun()

def load_csv():
    if os.path.exists(DATA_CSV):
        try:
            df = pd.read_csv(DATA_CSV)
            return df
        except Exception as e:
            st.error(f'Erro ao ler CSV: {e}')
            return None
    else:
        st.warning('Arquivo de histórico não encontrado: ' + DATA_CSV)
        return None

df = load_csv()

if df is not None:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader('Histórico de desligamentos')
    st.dataframe(df.sort_values('data_registro', ascending=False).reset_index(drop=True), use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.sidebar.markdown('### Ação manual')
with st.sidebar.form('form_manual'):
    nome = st.text_input('Nome completo')
    cpf = st.text_input('CPF (somente números)')
    email = st.text_input('E-mail corporativo')
    sistemas = {
        'ad': st.checkbox('Active Directory', value=True),
        'crm': st.checkbox('CRM JMJ', value=True),
        'saw': st.checkbox('SAW', value=True),
        'giu': st.checkbox('GIU Unimed', value=True),
        'ged': st.checkbox('GED Bye Bye Paper', value=True),
        'tasy': st.checkbox('Tasy EMR', value=True),
    }
    enviar_email = st.checkbox('Enviar e-mail de notificação ao TI (se disponível)', value=False)
    submit = st.form_submit_button('Lançar inativação manual')

if submit:
    # Validar
    if not cpf and not email:
        st.error('Informe pelo menos CPF ou E-mail para prosseguir.')
    else:
        st.info('Executando inativação — verifique logs no terminal se necessário...')
        # Importar função de processamento manual
        try:
            from inativar_manual import processar_sistema, enviar_email_notificacao_manual
        except Exception as e:
            st.error(f'Erro ao importar ferramentas de inativação: {e}')
        else:
            sistemas_selecionados = [k for k, v in sistemas.items() if v]
            resultados = {}
            for s in sistemas_selecionados:
                resultado = processar_sistema(s, cpf=cpf or None, email=email or None, nome=nome or None)
                resultados[s] = resultado

            # Mostrar resumo
            st.subheader('Resumo de execução')
            for sid, res in resultados.items():
                status = res.get('status')
                msg = res.get('msg', '')
                if status == 'sucesso':
                    st.success(f"{sid}: {msg}")
                elif status in ('ja_inativo', 'nao_encontrado', 'pulado'):
                    st.warning(f"{sid}: {msg}")
                else:
                    st.error(f"{sid}: {msg}")

            # Enviar email de notificação se pedido
            if enviar_email:
                try:
                    ok = enviar_email_notificacao_manual(cpf, email, nome, resultados)
                    if ok:
                        st.success('Email de notificação enviado.')
                    else:
                        st.warning('Falha ao enviar email (ver logs).')
                except Exception as e:
                    st.error(f'Erro ao enviar email: {e}')

            # Registrar no CSV histórico
            try:
                status_str = ';'.join([f"{k}:{v.get('status')}" for k, v in resultados.items()])
                novo = {
                    'data_registro': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'nome_colaborador': nome or '',
                    'cpf': cpf or '',
                    'email': email or '',
                    'matricula': '',
                    'setor': '',
                    'cargo': '',
                    'data_desligamento': datetime.now().strftime('%d/%m/%Y'),
                    'status_processamento': 'manual|' + status_str
                }

                # Append using pandas for simplicity
                df_new = pd.DataFrame([novo])
                if os.path.exists(DATA_CSV):
                    df_all = pd.concat([df, df_new], ignore_index=True)
                    df_all.to_csv(DATA_CSV, index=False)
                else:
                    df_new.to_csv(DATA_CSV, index=False)

                st.success('Registro salvo no histórico.')
            except Exception as e:
                st.error(f'Erro ao salvar no histórico: {e}')

st.markdown('---')
st.caption('Painel interno Unimed Oeste do Pará • Para rodar: streamlit run streamlit_app.py')
