import functools
import os
from datetime import date, datetime, timezone

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, session, url_for

from painel.ad_gestao import (
    DAY_INPUTS,
    DAYS_PT,
    ad_buscar_por_employee_id,
    ad_buscar_por_sam,
    ad_definir_bloqueio,
    ad_redefinir_senha,
    ad_search_users,
    ad_update_logon_hours_by_sam,
    build_logon_hours_bytes,
    criar_usuario_ad,
)
from painel.auth_ad import ErroAutenticacao, autenticar_usuario
from painel.exportacao import gerar_planilha_desligamentos
from painel.google_workspace import (
    criar_usuario_google,
    email_existe_no_google,
    listar_grupos,
    listar_membros_grupo,
    listar_unidades_organizacionais,
    listar_usuarios,
    obter_status_google,
)
from painel.infomed import InfomedConfigError, buscar_usuarios as infomed_buscar_usuarios
from painel.infomed import corrigir_preferencias as infomed_corrigir_preferencias
from painel.infomed import definir_ativo as infomed_definir_ativo
from painel.infomed import obter_usuario as infomed_obter_usuario
from painel.infomed import editar_dados as infomed_editar_dados
from painel.infomed import alterar_perfil as infomed_alterar_perfil
from painel.infomed import PERFIS_CONHECIDOS as INFOMED_PERFIS_CONHECIDOS
from google_admin import GoogleAdminConfigError
from painel.jobs import iniciar_job_inativacao, obter_status_job
from painel.rpa_status_jobs import NOMES_SISTEMAS, iniciar_job_status_sistemas, obter_status_job_sistemas
from painel.tangerino import (
    TangerinoConfigError,
    buscar_colaborador_por_cpf,
    fetch_employee_rows_page,
    fetch_vacation_rows_page,
    normalizar_cpf,
    to_date_yyyy_mm_dd,
)
from painel.utils import (
    contar_desligamentos_por_setor,
    formatar_cpf,
    gerar_senha_temporaria,
    ler_historico_desligamentos,
    ler_ultimas_linhas,
    mascarar_cpf,
    obter_demissoes_em_execucao,
    sugerir_login,
)
from painel.webhooks import listar_webhooks, reprocessar_webhook

painel_bp = Blueprint(
    "painel",
    __name__,
    url_prefix="/painel",
    template_folder="../templates/painel",
    static_folder="../static/painel",
    static_url_path="/static",
)

SISTEMAS_DISPONIVEIS = [
    ("ad", "Active Directory"),
    ("crm", "CRM JMJ"),
    ("saw", "SAW"),
    ("giu", "GIU Unimed"),
    ("ged", "GED Bye Bye Paper"),
    ("tasy", "Tasy EMR"),
    ("infomed", "Infomed"),
]

# todos os sistemas acima já suportam ativar E desativar - mantido como um set
# separado pra facilitar esmaecer na tela algum sistema que no futuro só suporte uma direção
SISTEMAS_SUPORTAM_ATIVAR = {"ad", "crm", "saw", "giu", "ged", "tasy", "infomed"}


def login_obrigatorio(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("usuario"):
            return redirect(url_for("painel.login", proximo=request.path))
        return view(*args, **kwargs)
    return wrapper


@painel_bp.route("/")
def index():
    return redirect(url_for("painel.dashboard"))


@painel_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("usuario"):
        return redirect(url_for("painel.dashboard"))

    if request.method == "POST":
        login_usuario = (request.form.get("login") or "").strip()
        senha = request.form.get("senha") or ""

        try:
            usuario = autenticar_usuario(login_usuario, senha)
            session.clear()
            session["usuario"] = usuario
            proximo = request.args.get("proximo")
            return redirect(proximo or url_for("painel.dashboard"))
        except ErroAutenticacao as erro:
            flash(str(erro), "erro")

    return render_template("login.html")


@painel_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("painel.login"))


LIMITE_MAXIMO_HISTORICO = 500


@painel_bp.route("/dashboard")
@login_obrigatorio
def dashboard():
    historico = ler_historico_desligamentos()
    for linha in historico:
        linha["cpf_mascarado"] = mascarar_cpf(linha.get("cpf", ""))

    return render_template(
        "dashboard.html",
        total_desligados=len(historico),
        em_execucao=obter_demissoes_em_execucao(),
        historico=historico[:LIMITE_MAXIMO_HISTORICO],
        limite_maximo=LIMITE_MAXIMO_HISTORICO,
    )


@painel_bp.route("/api/status-execucao")
@login_obrigatorio
def api_status_execucao():
    return jsonify({"em_execucao": obter_demissoes_em_execucao()})


@painel_bp.route("/api/desligamentos-por-setor")
@login_obrigatorio
def api_desligamentos_por_setor():
    inicio = request.args.get("inicio") or None
    fim = request.args.get("fim") or None
    historico = ler_historico_desligamentos()
    ranking = contar_desligamentos_por_setor(historico, inicio=inicio, fim=fim, top=10)
    return jsonify({"setores": ranking})


@painel_bp.route("/exportar/desligamentos.xlsx")
@login_obrigatorio
def exportar_desligamentos_xlsx():
    inicio = request.args.get("inicio") or None
    fim = request.args.get("fim") or None
    historico = ler_historico_desligamentos()
    planilha = gerar_planilha_desligamentos(historico, inicio=inicio, fim=fim)

    if inicio or fim:
        nome_arquivo = f"desligamentos_{inicio or 'inicio'}_a_{fim or 'hoje'}.xlsx"
    else:
        nome_arquivo = "desligamentos_todo_periodo.xlsx"

    return Response(
        planilha.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@painel_bp.route("/logs")
@login_obrigatorio
def logs():
    return render_template("logs.html")


@painel_bp.route("/api/logs")
@login_obrigatorio
def api_logs():
    from server import LOG_DIR

    arquivo = request.args.get("arquivo", "geral")
    nome_arquivo = "webhooks.log" if arquivo == "webhooks" else "integracao_solides.log"
    caminho = os.path.join(LOG_DIR, nome_arquivo)

    return jsonify({"linhas": ler_ultimas_linhas(caminho, quantidade=300)})


@painel_bp.route("/inativacao-manual", methods=["GET", "POST"])
@login_obrigatorio
def inativacao_manual():
    if request.method == "POST":
        cpf = (request.form.get("cpf") or "").strip() or None
        email = (request.form.get("email") or "").strip() or None
        nome = (request.form.get("nome") or "").strip() or None
        sistemas = request.form.getlist("sistemas")
        acao = request.form.get("acao", "desativar")
        if acao not in ("ativar", "desativar"):
            acao = "desativar"
        enviar_email = request.form.get("enviar_email") == "on"
        registrar_csv = request.form.get("registrar_csv") == "on"

        if not cpf and not email:
            flash("Informe pelo menos o CPF ou o email do colaborador.", "erro")
            return redirect(url_for("painel.inativacao_manual"))

        if not sistemas:
            mensagem = "Selecione ao menos um sistema para ativar." if acao == "ativar" else "Selecione ao menos um sistema para inativar."
            flash(mensagem, "erro")
            return redirect(url_for("painel.inativacao_manual"))

        job_id = iniciar_job_inativacao(
            cpf=cpf, email=email, nome=nome, sistemas=sistemas,
            enviar_email=enviar_email, registrar_csv=registrar_csv,
            usuario_login=session["usuario"]["login"], acao=acao,
        )
        return redirect(url_for("painel.inativacao_manual", job=job_id))

    job_id = request.args.get("job")
    return render_template(
        "manual.html", sistemas=SISTEMAS_DISPONIVEIS, job_id=job_id,
        sistemas_suportam_ativar=SISTEMAS_SUPORTAM_ATIVAR,
    )


@painel_bp.route("/api/inativacao-manual/status/<job_id>")
@login_obrigatorio
def api_status_job(job_id):
    job = obter_status_job(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado"}), 404
    return jsonify(job)


@painel_bp.route("/webhooks")
@login_obrigatorio
def webhooks():
    eventos = listar_webhooks(limit=200)
    for evento in eventos:
        evento["cpf_mascarado"] = mascarar_cpf(evento.get("cpf") or "")
    return render_template("webhooks.html", eventos=eventos)


@painel_bp.route("/api/webhooks")
@login_obrigatorio
def api_webhooks():
    eventos = listar_webhooks(limit=200)
    for evento in eventos:
        evento["cpf_mascarado"] = mascarar_cpf(evento.get("cpf") or "")
    return jsonify({"eventos": eventos})


@painel_bp.route("/webhooks/<webhook_id>/reprocessar", methods=["POST"])
@login_obrigatorio
def webhooks_reprocessar(webhook_id):
    try:
        novo_id = reprocessar_webhook(webhook_id)
        flash(f"Reprocessamento iniciado (novo evento {novo_id}).", "sucesso")
    except ValueError as erro:
        flash(str(erro), "erro")
    return redirect(url_for("painel.webhooks"))


@painel_bp.route("/ferias")
@login_obrigatorio
def ferias():
    from_s = request.args.get("from", "")
    to_s = request.args.get("to", "")
    status_filter = request.args.get("status", "").strip()
    only_now = request.args.get("now") == "1"

    try:
        current_page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        current_page = 1
    try:
        size = max(1, min(int(request.args.get("size", "20")), 200))
    except ValueError:
        size = 20

    rows, has_next, total_now, erro = [], False, 0, None
    try:
        rows, has_next, total_now = fetch_vacation_rows_page(
            from_d=to_date_yyyy_mm_dd(from_s), to_d=to_date_yyyy_mm_dd(to_s),
            status_filter=status_filter, only_now=only_now,
            ui_page=current_page, ui_page_size=size, api_page_size=size,
        )
    except TangerinoConfigError as e:
        erro = str(e)
    except Exception as e:
        erro = f"Falha ao consultar a API do Tangerino: {e}"

    return render_template(
        "ferias.html",
        rows=rows, from_=from_s, to_=to_s, status=status_filter, only_now=only_now,
        size=size, current_page=current_page, has_next_page=has_next,
        total_now=total_now, erro=erro,
    )


@painel_bp.route("/colaboradores")
@login_obrigatorio
def colaboradores():
    employment_status = request.args.get("employment_status", "").strip().upper()
    q = request.args.get("q", "").strip()
    show_fired = request.args.get("show_fired") == "1"
    sort_by = request.args.get("sort_by", "name").strip().lower()
    sort_dir = request.args.get("sort_dir", "asc").strip().lower()
    employee_mode = request.args.get("employee_mode", "fast").strip().lower()

    if sort_by not in ("name", "workplace", "job_role", "admission_date", "dismissal_date"):
        sort_by = "name"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "asc"
    if employee_mode not in ("fast", "global"):
        employee_mode = "fast"

    try:
        current_page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        current_page = 1
    try:
        size = max(1, min(int(request.args.get("size", "20")), 200))
    except ValueError:
        size = 20

    hoje = date.today()
    try:
        mes_admissao = int(request.args.get("mes", hoje.month))
        if not 1 <= mes_admissao <= 12:
            mes_admissao = hoje.month
    except ValueError:
        mes_admissao = hoje.month
    try:
        ano_admissao = int(request.args.get("ano", hoje.year))
    except ValueError:
        ano_admissao = hoje.year

    rows, has_next, erro = [], False, None
    try:
        rows, has_next = fetch_employee_rows_page(
            employment_status=employment_status, q=q, show_fired=show_fired,
            sort_by=sort_by, sort_dir=sort_dir, employee_mode=employee_mode,
            ui_page=current_page, ui_page_size=size, api_page_size=size,
        )
        for linha in rows:
            linha["cpf_formatado"] = formatar_cpf(linha.get("cpf"))
    except TangerinoConfigError as e:
        erro = str(e)
    except Exception as e:
        erro = f"Falha ao consultar a API do Tangerino: {e}"

    total_admitidos_mes, erro_admitidos_mes = None, None
    try:
        todos_colaboradores, _ = fetch_employee_rows_page(
            employment_status="", q="", show_fired=True,
            sort_by="name", sort_dir="asc", employee_mode="global",
            ui_page=1, ui_page_size=100000, api_page_size=200,
        )
        total_admitidos_mes = 0
        for c in todos_colaboradores:
            ts = c.get("admission_ts")
            if not ts:
                continue
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            if dt.year == ano_admissao and dt.month == mes_admissao:
                total_admitidos_mes += 1
    except TangerinoConfigError as e:
        erro_admitidos_mes = str(e)
    except Exception as e:
        erro_admitidos_mes = f"Falha ao consultar a API do Tangerino: {e}"

    return render_template(
        "colaboradores.html",
        rows=rows, employment_status=employment_status, q=q, show_fired=show_fired,
        sort_by=sort_by, sort_dir=sort_dir, employee_mode=employee_mode,
        size=size, current_page=current_page, has_next_page=has_next, erro=erro,
        mes_admissao=mes_admissao, ano_admissao=ano_admissao,
        mes_atual=hoje.month, ano_atual=hoje.year,
        total_admitidos_mes=total_admitidos_mes, erro_admitidos_mes=erro_admitidos_mes,
    )


UTC_OFFSET_HOURS = int(os.getenv("UTC_OFFSET_HOURS", "-3"))


@painel_bp.route("/usuarios-ad")
@login_obrigatorio
def usuarios_ad():
    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "todos").strip()
    ou_filter = request.args.get("ou", "todos").strip()
    try:
        current_page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        current_page = 1
    try:
        size = max(1, min(int(request.args.get("size", "20")), 200))
    except ValueError:
        size = 20

    erro = None
    users = []
    try:
        users = ad_search_users(q, UTC_OFFSET_HOURS)
    except Exception as e:
        erro = f"Falha ao consultar o Active Directory: {e}"

    ou_options = sorted({u["ou"] for u in users if u.get("ou")}, key=str.lower)

    if status_filter == "ativo":
        users = [u for u in users if not u["disabled"]]
    elif status_filter == "desativado":
        users = [u for u in users if u["disabled"]]

    if ou_filter != "todos":
        users = [u for u in users if u.get("ou") == ou_filter]

    total_encontrados = len(users)
    inicio = (current_page - 1) * size
    users_pagina = users[inicio: inicio + size]
    has_next_page = total_encontrados > inicio + size

    return render_template(
        "usuarios_ad.html",
        users=users_pagina, q=q, status_filter=status_filter, ou_filter=ou_filter,
        ou_options=ou_options, dias=DAYS_PT, erro=erro,
        size=size, current_page=current_page, has_next_page=has_next_page,
    )


@painel_bp.route("/google-workspace", endpoint="google_workspace")
@login_obrigatorio
def tela_google_workspace():
    aba = request.args.get("aba", "usuarios")
    if aba not in ("usuarios", "grupos", "unidades"):
        aba = "usuarios"

    q = request.args.get("q", "").strip()
    grupo_selecionado = request.args.get("grupo", "").strip()

    erro = None
    usuarios, grupos, unidades, membros_grupo = [], [], [], []

    try:
        if aba == "usuarios":
            usuarios = listar_usuarios(query=q or None)
        elif aba == "grupos":
            grupos = listar_grupos()
            if grupo_selecionado:
                membros_grupo = listar_membros_grupo(grupo_selecionado)
        elif aba == "unidades":
            unidades = listar_unidades_organizacionais()
    except GoogleAdminConfigError as e:
        erro = str(e)
    except Exception as e:
        erro = f"Falha ao consultar o Google Workspace: {e}"

    return render_template(
        "google_workspace.html",
        aba=aba, q=q, erro=erro,
        usuarios=usuarios, grupos=grupos, unidades=unidades,
        grupo_selecionado=grupo_selecionado, membros_grupo=membros_grupo,
    )


@painel_bp.route("/api/colaboradores/<cpf>/acesso")
@login_obrigatorio
def api_colaborador_acesso(cpf):
    cpf_normalizado = normalizar_cpf(cpf)
    if not cpf_normalizado:
        return jsonify({"erro": "CPF inválido."}), 400

    try:
        usuario_ad = ad_buscar_por_employee_id(cpf_normalizado, UTC_OFFSET_HOURS)
    except Exception as e:
        return jsonify({"erro": f"Falha ao consultar o Active Directory: {e}"}), 502

    if not usuario_ad:
        return jsonify({"erro": "Nenhum usuário do AD encontrado com esse CPF (employeeID)."}), 404

    try:
        dados_tangerino = buscar_colaborador_por_cpf(cpf_normalizado)
    except Exception:
        dados_tangerino = None

    return jsonify({"ad": usuario_ad, "tangerino": dados_tangerino})


@painel_bp.route("/api/colaboradores/<cpf>/sistemas")
@login_obrigatorio
def api_colaborador_sistemas(cpf):
    cpf_normalizado = normalizar_cpf(cpf)
    if not cpf_normalizado:
        return jsonify({"erro": "CPF inválido."}), 400

    sistemas = []

    usuario_ad = None
    try:
        usuario_ad = ad_buscar_por_employee_id(cpf_normalizado, UTC_OFFSET_HOURS)
    except Exception as e:
        sistemas.append({"nome": "Active Directory", "status": "erro", "detalhe": str(e)})

    if usuario_ad:
        sistemas.append({
            "nome": "Active Directory",
            "status": "inativo" if usuario_ad["disabled"] else "ativo",
            "detalhe": usuario_ad["sam"],
        })
    elif not any(s["nome"] == "Active Directory" for s in sistemas):
        sistemas.append({"nome": "Active Directory", "status": "nao_encontrado", "detalhe": "Sem conta com esse CPF"})

    email = (usuario_ad or {}).get("mail")
    if email:
        try:
            status_google = obter_status_google(email)
        except Exception as e:
            sistemas.append({"nome": "Google Workspace", "status": "erro", "detalhe": str(e)})
        else:
            if status_google["existe"]:
                sistemas.append({
                    "nome": "Google Workspace",
                    "status": "inativo" if status_google["suspenso"] else "ativo",
                    "detalhe": email,
                })
            else:
                sistemas.append({"nome": "Google Workspace", "status": "nao_encontrado", "detalhe": email})
    else:
        sistemas.append({"nome": "Google Workspace", "status": "nao_encontrado", "detalhe": "Sem email no AD pra checar"})

    nome_conta = usuario_ad.get("sam") if usuario_ad else None
    nome_completo = usuario_ad.get("displayName") if usuario_ad else None

    job_id = None
    if email and nome_conta:
        job_id = iniciar_job_status_sistemas(
            email=email, cpf=cpf_normalizado, nome_completo=nome_completo, nome_conta=nome_conta,
        )
    else:
        for sid, nome_sistema in NOMES_SISTEMAS.items():
            sistemas.append({
                "nome": nome_sistema, "status": "erro",
                "detalhe": "Sem email/usuário do AD pra consultar esse sistema",
            })

    return jsonify({"sistemas": sistemas, "job_id": job_id})


@painel_bp.route("/api/colaboradores/sistemas-rpa/<job_id>")
@login_obrigatorio
def api_colaborador_sistemas_rpa_status(job_id):
    job = obter_status_job_sistemas(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado (pode ter expirado)."}), 404

    sistemas = [
        {"nome": NOMES_SISTEMAS[sid], "status": dados["status"], "detalhe": dados["detalhe"]}
        for sid, dados in job["resultados"].items()
    ]
    return jsonify({"sistemas": sistemas, "concluido": job["concluido"]})


@painel_bp.route("/api/usuarios-ad/redefinir-senha", methods=["POST"])
@login_obrigatorio
def api_ad_redefinir_senha():
    sam = (request.form.get("sam") or "").strip()
    forcar_troca = request.form.get("forcar_troca") == "1"
    if not sam:
        return jsonify({"erro": "sam é obrigatório."}), 400

    nova_senha = gerar_senha_temporaria()
    try:
        ok, mensagem = ad_redefinir_senha(sam, nova_senha, forcar_troca)
    except Exception as e:
        return jsonify({"erro": str(e)}), 502

    if not ok:
        return jsonify({"erro": mensagem}), 400
    return jsonify({"mensagem": mensagem, "senha": nova_senha})


@painel_bp.route("/api/usuarios-ad/bloqueio", methods=["POST"])
@login_obrigatorio
def api_ad_definir_bloqueio():
    sam = (request.form.get("sam") or "").strip()
    bloquear = request.form.get("bloquear") == "1"
    if not sam:
        return jsonify({"erro": "sam é obrigatório."}), 400

    try:
        ok, mensagem = ad_definir_bloqueio(sam, bloquear)
    except Exception as e:
        return jsonify({"erro": str(e)}), 502

    if not ok:
        return jsonify({"erro": mensagem}), 400
    return jsonify({"mensagem": mensagem, "bloqueado": bloquear})


@painel_bp.route("/api/usuarios-ad/horario-ajax", methods=["POST"])
@login_obrigatorio
def api_ad_definir_horario_ajax():
    sam = (request.form.get("sam") or "").strip()
    edit_mode = request.form.get("edit_mode", "todos")
    ranges_all = request.form.get("ranges_all", "")
    per_day_ranges = {idx: request.form.get(f"ranges_{codigo}", "") for codigo, _, idx in DAY_INPUTS}

    if not sam:
        return jsonify({"erro": "sam é obrigatório."}), 400

    data, parse_err = build_logon_hours_bytes(edit_mode, ranges_all, per_day_ranges, UTC_OFFSET_HOURS)
    if parse_err:
        return jsonify({"erro": parse_err}), 400

    try:
        ok, mensagem = ad_update_logon_hours_by_sam(sam, data or b"")
    except Exception as e:
        return jsonify({"erro": str(e)}), 502

    if not ok:
        return jsonify({"erro": mensagem}), 400
    return jsonify({"mensagem": mensagem})


@painel_bp.route("/api/tangerino/debug-employee")
@login_obrigatorio
def api_tangerino_debug_employee():
    from painel.tangerino import (
        buscar_todos_employees_brutos,
        build_http_session,
        get_first_present,
        get_headers_from_env,
        get_timeout,
    )

    cpf_busca = normalizar_cpf(request.args.get("cpf"))
    quantidade_amostra = int(request.args.get("amostra", "5"))

    try:
        headers = get_headers_from_env()
        session = build_http_session()
        timeout = get_timeout()
    except TangerinoConfigError as e:
        return jsonify({"erro": str(e)}), 400

    try:
        brutos = buscar_todos_employees_brutos(session, headers, timeout, incluir_demitidos=True)
    except Exception as e:
        return jsonify({"erro": f"Falha ao consultar o Tangerino: {e}"}), 502

    amostras = []
    com_cpf_preenchido = 0
    sem_cpf = 0
    encontrado = None

    for emp in brutos:
        cpf_bruto = get_first_present(emp, ("cpf", "cpfNumber", "documento", "numeroCpf", "docNumber"))
        cpf_normalizado = normalizar_cpf(cpf_bruto)
        if cpf_normalizado:
            com_cpf_preenchido += 1
        else:
            sem_cpf += 1

        if len(amostras) < quantidade_amostra:
            amostras.append({
                "id": emp.get("id"), "name": emp.get("name"),
                "cpf_bruto": cpf_bruto, "cpf_normalizado": cpf_normalizado or None,
            })

        if cpf_busca and cpf_normalizado == cpf_busca:
            encontrado = emp

    return jsonify({
        "cpf_buscado": cpf_busca or None,
        "encontrado": encontrado,
        "total_colaboradores_varridos": len(brutos),
        "com_cpf_preenchido": com_cpf_preenchido,
        "sem_cpf_preenchido": sem_cpf,
        "amostra_bruta": amostras,
    })


@painel_bp.route("/api/colaboradores/buscar-cpf")
@login_obrigatorio
def api_buscar_colaborador_cpf():
    cpf = normalizar_cpf(request.args.get("cpf"))
    if not cpf:
        return jsonify({"erro": "Informe o CPF."}), 400

    try:
        colaborador = buscar_colaborador_por_cpf(cpf)
    except TangerinoConfigError as e:
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        return jsonify({"erro": f"Falha ao consultar o Tangerino: {e}"}), 502

    if not colaborador:
        return jsonify({"erro": "Nenhum colaborador encontrado com esse CPF no Tangerino."}), 404

    colaborador["login_sugerido"] = sugerir_login(colaborador["nome"])

    ad_existente = None
    try:
        ad_existente = ad_buscar_por_employee_id(cpf, UTC_OFFSET_HOURS)
    except Exception:
        pass

    if not ad_existente and colaborador["login_sugerido"]:
        try:
            ad_existente = ad_buscar_por_sam(colaborador["login_sugerido"])
        except Exception:
            pass

    colaborador["ad_existente"] = ad_existente
    return jsonify(colaborador)


@painel_bp.route("/api/google-workspace/verificar-email")
@login_obrigatorio
def api_verificar_email_google():
    email = (request.args.get("email") or "").strip().lower()
    if not email:
        return jsonify({"erro": "Informe o email."}), 400

    try:
        existe = email_existe_no_google(email)
    except GoogleAdminConfigError as e:
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        return jsonify({"erro": f"Falha ao consultar o Google Workspace: {e}"}), 502

    return jsonify({"existe": existe})


@painel_bp.route("/colaboradores/novo-acesso", methods=["GET", "POST"])
@login_obrigatorio
def colaboradores_novo_acesso():
    if request.method == "GET":
        return render_template("novo_acesso.html", dominio_google=os.getenv("GOOGLE_WORKSPACE_DOMAIN", ""))

    cpf = normalizar_cpf(request.form.get("cpf"))
    nome_completo = (request.form.get("nome_completo") or "").strip()
    setor = (request.form.get("setor") or "").strip()
    cargo = (request.form.get("cargo") or "").strip()
    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip().lower()

    erros = []
    if not cpf:
        erros.append("CPF é obrigatório.")
    if not nome_completo:
        erros.append("Nome completo é obrigatório.")
    if not username:
        erros.append("Nome de usuário é obrigatório.")
    if not email:
        erros.append("Email é obrigatório.")

    if erros:
        for erro in erros:
            flash(erro, "erro")
        return render_template("novo_acesso.html", dominio_google=os.getenv("GOOGLE_WORKSPACE_DOMAIN", ""), form=request.form)

    try:
        usuario_existente = ad_buscar_por_employee_id(cpf, UTC_OFFSET_HOURS)
    except Exception as e:
        flash(f"Não foi possível validar o CPF no Active Directory: {e}", "erro")
        return render_template("novo_acesso.html", dominio_google=os.getenv("GOOGLE_WORKSPACE_DOMAIN", ""), form=request.form)

    if usuario_existente:
        flash(f"Esse CPF já está cadastrado no AD (usuário: {usuario_existente['sam']}).", "erro")
        return render_template("novo_acesso.html", dominio_google=os.getenv("GOOGLE_WORKSPACE_DOMAIN", ""), form=request.form)

    try:
        if email_existe_no_google(email):
            flash(f"Já existe uma conta no Google Workspace com o email {email}.", "erro")
            return render_template("novo_acesso.html", dominio_google=os.getenv("GOOGLE_WORKSPACE_DOMAIN", ""), form=request.form)
    except GoogleAdminConfigError as e:
        flash(str(e), "erro")
        return render_template("novo_acesso.html", dominio_google=os.getenv("GOOGLE_WORKSPACE_DOMAIN", ""), form=request.form)
    except Exception as e:
        flash(f"Não foi possível validar o email no Google Workspace: {e}", "erro")
        return render_template("novo_acesso.html", dominio_google=os.getenv("GOOGLE_WORKSPACE_DOMAIN", ""), form=request.form)

    partes_nome = nome_completo.split(" ", 1)
    primeiro_nome = partes_nome[0]
    sobrenome = partes_nome[1] if len(partes_nome) > 1 else primeiro_nome

    senha_ad = gerar_senha_temporaria()
    senha_google = gerar_senha_temporaria()

    try:
        ok, mensagem, _dn = criar_usuario_ad(nome_completo, setor, username, email, cpf, senha_ad)
        resultado_ad = {"status": "sucesso" if ok else "erro", "mensagem": mensagem, "senha": senha_ad if ok else None}
    except Exception as e:
        resultado_ad = {"status": "erro", "mensagem": str(e), "senha": None}

    try:
        criar_usuario_google(primeiro_nome, sobrenome, email, senha_google, cargo=cargo or None, departamento=setor or None)
        resultado_google = {"status": "sucesso", "mensagem": "Usuário criado com sucesso no Google Workspace.", "senha": senha_google}
    except Exception as e:
        resultado_google = {"status": "erro", "mensagem": str(e), "senha": None}

    return render_template(
        "novo_acesso_resultado.html",
        nome_completo=nome_completo, email=email, username=username,
        resultado_ad=resultado_ad, resultado_google=resultado_google,
    )


@painel_bp.route("/infomed", endpoint="infomed")
@login_obrigatorio
def tela_infomed():
    q = request.args.get("q", "").strip()
    erro = None
    usuarios = []

    if q:
        try:
            usuarios = infomed_buscar_usuarios(q)
        except InfomedConfigError as e:
            erro = str(e)
        except Exception as e:
            erro = f"Falha ao consultar o Infomed: {e}"

    perfis_disponiveis = sorted(INFOMED_PERFIS_CONHECIDOS.items(), key=lambda item: item[1])
    return render_template("infomed.html", q=q, usuarios=usuarios, erro=erro, perfis_disponiveis=perfis_disponiveis)


@painel_bp.route("/api/infomed/usuario/<codigo>")
@login_obrigatorio
def api_infomed_usuario(codigo):
    try:
        usuario = infomed_obter_usuario(codigo)
    except InfomedConfigError as e:
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        return jsonify({"erro": f"Falha ao consultar o Infomed: {e}"}), 502

    if not usuario:
        return jsonify({"erro": "Usuário não encontrado."}), 404
    return jsonify(usuario)


@painel_bp.route("/api/infomed/usuario/<codigo>/perfil", methods=["POST"])
@login_obrigatorio
def api_infomed_alterar_perfil(codigo):
    try:
        per_codigo = int(request.form.get("per_codigo", ""))
    except ValueError:
        return jsonify({"erro": "Código de perfil inválido."}), 400

    ativo = request.form.get("ativo") == "1"

    try:
        ok, mensagem = infomed_alterar_perfil(codigo, per_codigo, ativo)
    except InfomedConfigError as e:
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        return jsonify({"erro": f"Falha ao atualizar o Infomed: {e}"}), 502

    if not ok:
        return jsonify({"erro": mensagem}), 400
    return jsonify({"mensagem": mensagem, "codigo": per_codigo, "ativo": ativo})


@painel_bp.route("/api/infomed/usuario/<codigo>/dados", methods=["POST"])
@login_obrigatorio
def api_infomed_editar_dados(codigo):
    nome = (request.form.get("nome") or "").strip()
    email = (request.form.get("email") or "").strip()

    if not nome:
        return jsonify({"erro": "Nome é obrigatório."}), 400

    try:
        ok, mensagem = infomed_editar_dados(codigo, nome, email)
    except InfomedConfigError as e:
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        return jsonify({"erro": f"Falha ao atualizar o Infomed: {e}"}), 502

    if not ok:
        return jsonify({"erro": mensagem}), 400
    return jsonify({"mensagem": mensagem, "nome": nome, "email": email})


@painel_bp.route("/api/infomed/usuario/<codigo>/ativo", methods=["POST"])
@login_obrigatorio
def api_infomed_definir_ativo(codigo):
    ativo = request.form.get("ativo") == "1"
    try:
        ok, mensagem = infomed_definir_ativo(codigo, ativo)
    except InfomedConfigError as e:
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        return jsonify({"erro": f"Falha ao atualizar o Infomed: {e}"}), 502

    if not ok:
        return jsonify({"erro": mensagem}), 400
    return jsonify({"mensagem": mensagem, "ativo": ativo})


@painel_bp.route("/api/infomed/usuario/<codigo>/preferencias", methods=["POST"])
@login_obrigatorio
def api_infomed_corrigir_preferencias(codigo):
    try:
        dias = int(request.form.get("dias_expiracao_senha", ""))
        tentativas = int(request.form.get("tentativas_login", ""))
    except ValueError:
        return jsonify({"erro": "Dias de expiração e tentativas de login precisam ser números."}), 400

    salvar_preferencias = request.form.get("salvar_preferencias") == "1"

    try:
        ok, mensagem = infomed_corrigir_preferencias(codigo, dias, tentativas, salvar_preferencias)
    except InfomedConfigError as e:
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        return jsonify({"erro": f"Falha ao atualizar o Infomed: {e}"}), 502

    if not ok:
        return jsonify({"erro": mensagem}), 400
    return jsonify({"mensagem": mensagem})
