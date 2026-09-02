import threading
import uuid
from datetime import datetime

jobs_manuais = {}
jobs_lock = threading.Lock()


def iniciar_job_inativacao(cpf, email, nome, sistemas, enviar_email, registrar_csv, usuario_login, acao='desativar'):
    job_id = uuid.uuid4().hex[:12]

    job = {
        "id": job_id,
        "usuario": usuario_login,
        "cpf": cpf,
        "email": email,
        "nome": nome,
        "sistemas": sistemas,
        "acao": acao,
        "iniciado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "concluido": False,
        "resultados": {sid: {"status": "pendente", "msg": ""} for sid in sistemas},
    }

    with jobs_lock:
        jobs_manuais[job_id] = job

    thread = threading.Thread(
        target=_executar_job,
        args=(job_id, cpf, email, nome, sistemas, enviar_email, registrar_csv, acao),
        daemon=True,
    )
    thread.start()

    return job_id


def _executar_job(job_id, cpf, email, nome, sistemas, enviar_email, registrar_csv, acao='desativar'):
    from inativar_manual import processar_sistema, enviar_email_notificacao_manual

    resultados = {}

    for sistema_id in sistemas:
        with jobs_lock:
            jobs_manuais[job_id]["resultados"][sistema_id]["status"] = "executando"

        try:
            resultado = processar_sistema(sistema_id, cpf=cpf, email=email, nome=nome, acao=acao)
        except Exception as e:
            resultado = {"status": "erro", "msg": str(e)}

        resultados[sistema_id] = resultado

        with jobs_lock:
            jobs_manuais[job_id]["resultados"][sistema_id] = {
                "status": resultado.get("status", "erro"),
                "msg": resultado.get("msg", ""),
            }

    if registrar_csv and acao == 'desativar':
        try:
            from server import registrar_desligamento_csv

            status_geral = "sucesso" if all(
                r.get("status") in ("sucesso", "ja_inativo", "pulado")
                for r in resultados.values()
            ) else "parcial"

            dados_colaborador = {
                "nome": nome or "N/A",
                "email": email or "N/A",
                "departamento": {"nome": "N/A"},
                "cargo": {"nome": "N/A"},
                "matricula": "N/A",
                "data_demissao": datetime.now().strftime("%d/%m/%Y"),
            }
            registrar_desligamento_csv(dados_colaborador, cpf, status_processamento=f"manual-{acao}-{status_geral}")
        except Exception as e:
            with jobs_lock:
                jobs_manuais[job_id]["erro_csv"] = str(e)

    if enviar_email:
        try:
            enviar_email_notificacao_manual(cpf, email, nome, resultados)
        except Exception as e:
            with jobs_lock:
                jobs_manuais[job_id]["erro_email"] = str(e)

    with jobs_lock:
        jobs_manuais[job_id]["concluido"] = True


def obter_status_job(job_id):
    with jobs_lock:
        job = jobs_manuais.get(job_id)
        return dict(job) if job else None
