import threading
import uuid

jobs_status_sistemas = {}
jobs_status_lock = threading.Lock()

SISTEMAS_RPA = ["crm", "saw", "giu", "ged", "tasy", "infomed"]

NOMES_SISTEMAS = {
    "crm": "CRM JMJ",
    "saw": "SAW",
    "giu": "GIU Unimed",
    "ged": "GED Bye Bye Paper",
    "tasy": "Tasy EMR",
    "infomed": "Infomed",
}


def _normalizar_status(valor_bruto):
    if valor_bruto in ("ativo", "inativo"):
        return valor_bruto
    if valor_bruto == 3:
        return "nao_encontrado"
    return "erro"


def _checar_um_sistema(job_id, sistema_id, email, cpf, nome_completo, nome_conta):
    try:
        if sistema_id == "crm":
            from rpa_crm import consultar_status_crm
            status_bruto, detalhe = consultar_status_crm(email)
        elif sistema_id == "saw":
            from rpa_saw import consultar_status_saw
            status_bruto, detalhe = consultar_status_saw(email)
        elif sistema_id == "giu":
            from rpa_giu import consultar_status_giu
            status_bruto, detalhe = consultar_status_giu(cpf)
        elif sistema_id == "ged":
            from rpa_ged import consultar_status_ged
            status_bruto, detalhe = consultar_status_ged(email)
        elif sistema_id == "tasy":
            from rpa_tasy import consultar_status_tasy
            status_bruto, detalhe = consultar_status_tasy(nome_completo, nome_conta)
        elif sistema_id == "infomed":
            from rpa_infomed import consultar_status_infomed
            status_bruto, detalhe = consultar_status_infomed(email)
        else:
            status_bruto, detalhe = "erro", "Sistema desconhecido"
    except Exception as e:
        status_bruto, detalhe = "erro", str(e)

    status = _normalizar_status(status_bruto)
    if status == "erro" and not detalhe:
        detalhe = "Falha ao consultar."

    with jobs_status_lock:
        if job_id in jobs_status_sistemas:
            jobs_status_sistemas[job_id]["resultados"][sistema_id] = {"status": status, "detalhe": detalhe}


def _executar_checagens(job_id, email, cpf, nome_completo, nome_conta):
    threads = []
    for sistema_id in SISTEMAS_RPA:
        t = threading.Thread(
            target=_checar_um_sistema,
            args=(job_id, sistema_id, email, cpf, nome_completo, nome_conta),
            daemon=True,
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    with jobs_status_lock:
        if job_id in jobs_status_sistemas:
            jobs_status_sistemas[job_id]["concluido"] = True


def iniciar_job_status_sistemas(email, cpf, nome_completo, nome_conta):
    job_id = uuid.uuid4().hex[:12]

    job = {
        "id": job_id,
        "resultados": {sid: {"status": "verificando", "detalhe": None} for sid in SISTEMAS_RPA},
        "concluido": False,
    }
    with jobs_status_lock:
        jobs_status_sistemas[job_id] = job

    thread = threading.Thread(
        target=_executar_checagens,
        args=(job_id, email, cpf, nome_completo, nome_conta),
        daemon=True,
    )
    thread.start()

    return job_id


def obter_status_job_sistemas(job_id):
    with jobs_status_lock:
        job = jobs_status_sistemas.get(job_id)
        return dict(job) if job else None
