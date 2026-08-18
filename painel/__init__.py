"""
Painel web da Integração Solides.

Blueprint Flask registrado em server.py (app.register_blueprint(painel_bp)),
sob o prefixo /painel. Reaproveita as configurações e funções já existentes
em server.py e inativar_manual.py - nenhuma dependência nova é necessária.
"""

import functools
import os

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, session, url_for

from painel.auth_ad import ErroAutenticacao, autenticar_usuario
from painel.exportacao import gerar_planilha_desligamentos
from painel.jobs import iniciar_job_inativacao, obter_status_job
from painel.utils import (
    contar_desligamentos_por_setor,
    ler_historico_desligamentos,
    ler_ultimas_linhas,
    mascarar_cpf,
    obter_demissoes_em_execucao,
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

# Sistemas disponíveis para a inativação manual (mesmos aceitos por inativar_manual.py)
SISTEMAS_DISPONIVEIS = [
    ("ad", "Active Directory"),
    ("crm", "CRM JMJ"),
    ("saw", "SAW"),
    ("giu", "GIU Unimed"),
    ("ged", "GED Bye Bye Paper"),
    ("tasy", "Tasy EMR"),
]


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
    historico = ler_historico_desligamentos()  # sempre sobre a base completa, sem o limite da tabela
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
        enviar_email = request.form.get("enviar_email") == "on"
        registrar_csv = request.form.get("registrar_csv") == "on"

        if not cpf and not email:
            flash("Informe pelo menos o CPF ou o email do colaborador.", "erro")
            return redirect(url_for("painel.inativacao_manual"))

        if not sistemas:
            flash("Selecione ao menos um sistema para inativar.", "erro")
            return redirect(url_for("painel.inativacao_manual"))

        job_id = iniciar_job_inativacao(
            cpf=cpf, email=email, nome=nome, sistemas=sistemas,
            enviar_email=enviar_email, registrar_csv=registrar_csv,
            usuario_login=session["usuario"]["login"],
        )
        return redirect(url_for("painel.inativacao_manual", job=job_id))

    job_id = request.args.get("job")
    return render_template("manual.html", sistemas=SISTEMAS_DISPONIVEIS, job_id=job_id)


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
