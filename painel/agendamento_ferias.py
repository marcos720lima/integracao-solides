"""Agendamentos de desativação de acessos por férias.

Guarda, em data/agendamentos_ferias.json, períodos em que os acessos de um
colaborador devem ficar inativos. Uma tarefa diária (tarefa_ferias.py, via
Task Scheduler às 7h) aplica as ações:

  - no dia de INÍCIO: inativa os sistemas escolhidos e registra QUAIS estavam
    ativos naquele momento (só esses serão reativados depois);
  - no dia de FIM (ou depois): reativa apenas os que estavam ativos antes.

Estado de cada agendamento: 'agendado' -> 'inativado' -> 'reativado'
(ou 'erro_inativacao' / 'erro_reativacao' quando falha, para retentar).
"""

import os
import json
import uuid
import threading
from datetime import date, datetime

_lock = threading.Lock()

# sistemas que fazem sentido pausar em férias (mesmos ids do inativar_manual)
SISTEMAS_FERIAS_PADRAO = ["ad", "google", "nextqs", "giu"]


def _caminho():
    from server import DATA_DIR
    return os.path.join(DATA_DIR, "agendamentos_ferias.json")


def _carregar_bruto():
    caminho = _caminho()
    if not os.path.exists(caminho):
        return []
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _salvar_bruto(lista):
    caminho = _caminho()
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lista, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, caminho)  # escrita atômica: nunca deixa o arquivo pela metade


def listar_agendamentos(incluir_encerrados=True):
    with _lock:
        itens = _carregar_bruto()
    if incluir_encerrados:
        return itens
    return [a for a in itens if a.get("estado") not in ("reativado", "cancelado")]


def criar_agendamento(nome, cpf, email, data_inicio, data_fim, sistemas=None):
    """Cria um agendamento. Datas no formato 'YYYY-MM-DD'. Retorna o registro."""
    if not (nome and (cpf or email) and data_inicio and data_fim):
        raise ValueError("Nome, um identificador (CPF ou email), início e fim são obrigatórios.")
    if data_fim < data_inicio:
        raise ValueError("A data de fim não pode ser anterior à de início.")

    registro = {
        "id": uuid.uuid4().hex[:12],
        "nome": nome,
        "cpf": cpf or "",
        "email": email or "",
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "sistemas": sistemas or list(SISTEMAS_FERIAS_PADRAO),
        "estado": "agendado",
        "sistemas_reativar": [],       # preenchido na inativação: o que estava ativo
        "criado_em": datetime.now().isoformat(timespec="seconds"),
        "historico": [],
        "tentativas_falha": 0,
    }
    with _lock:
        itens = _carregar_bruto()
        itens.append(registro)
        _salvar_bruto(itens)
    return registro


def cancelar_agendamento(id_agendamento):
    with _lock:
        itens = _carregar_bruto()
        for a in itens:
            if a["id"] == id_agendamento:
                # só cancela o que ainda não inativou; se já inativou, não mexe
                # (a reativação ainda precisa acontecer)
                if a["estado"] == "agendado":
                    a["estado"] = "cancelado"
                    a["historico"].append(_evento("cancelado manualmente"))
                    _salvar_bruto(itens)
                    return True, "Agendamento cancelado."
                return False, f"Não é possível cancelar: estado atual '{a['estado']}'."
        return False, "Agendamento não encontrado."


def atualizar(registro):
    """Regrava um registro já modificado (usado pela tarefa diária)."""
    with _lock:
        itens = _carregar_bruto()
        for i, a in enumerate(itens):
            if a["id"] == registro["id"]:
                itens[i] = registro
                _salvar_bruto(itens)
                return
        itens.append(registro)
        _salvar_bruto(itens)


def _evento(texto):
    return {"quando": datetime.now().isoformat(timespec="seconds"), "texto": texto}


def _hoje():
    return date.today().isoformat()


def pendentes_para_inativar(hoje=None):
    hoje = hoje or _hoje()
    return [a for a in listar_agendamentos()
            if a["estado"] in ("agendado", "erro_inativacao")
            and a["data_inicio"] <= hoje <= a["data_fim"]]


def pendentes_para_reativar(hoje=None):
    hoje = hoje or _hoje()
    return [a for a in listar_agendamentos()
            if a["estado"] in ("inativado", "erro_reativacao")
            and a["data_fim"] < hoje]
